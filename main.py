import os
import json
import csv
import io
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from contextlib import asynccontextmanager
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
)
from uagents_core.envelope import Envelope
from typing import cast
from uagents_core.utils.messages import parse_envelope, send_message_to_agent
from uagents_core.identity import Identity


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

identity = Identity.from_seed(os.getenv("AGENT_SEED_PHRASE"), 0)
load_dotenv()

app = FastAPI(lifespan=lifespan)

client = OpenAI(
    api_key=os.getenv("ASI_ONE_API_KEY"),
    base_url="https://api.asi1.ai/v1",
)

DB_NAME = "cashguard.db"
chat_history = []

CATEGORIES = [
    "food",
    "transport",
    "education",
    "entertainment",
    "shopping",
    "bills",
    "health",
    "other",
]


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            note TEXT NOT NULL,
            expense_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)  
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            currency TEXT NOT NULL DEFAULT 'INR'
        )
    """)

    conn.execute("""
        INSERT OR IGNORE INTO user_settings (id, currency)
            VALUES (1, 'INR')
    """)
    
    

    conn.execute("""
        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            source TEXT NOT NULL,
            income_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            monthly_budget REAL NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE NOT NULL,
            monthly_limit REAL NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            saved_amount REAL NOT NULL DEFAULT 0,
            target_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            due_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        INSERT OR IGNORE INTO settings (id, monthly_budget)
        VALUES (1, 10000)
    """)

    conn.commit()
    conn.close()


def month_start(reference=None):
    reference = reference or date.today()
    return reference.replace(day=1)


def next_month_start(reference=None):
    reference = reference or date.today()

    if reference.month == 12:
        return reference.replace(year=reference.year + 1, month=1, day=1)

    return reference.replace(month=reference.month + 1, day=1)


def get_budget():
    conn = get_db()
    row = conn.execute(
        "SELECT monthly_budget FROM settings WHERE id = 1"
    ).fetchone()
    conn.close()

    return row["monthly_budget"]


def set_budget(amount):
    conn = get_db()
    conn.execute(
        "UPDATE settings SET monthly_budget = ? WHERE id = 1",
        (amount,)
    )
    conn.commit()
    conn.close()


def add_expense(amount, category, note, expense_date):
    conn = get_db()

    conn.execute("""
        INSERT INTO expenses (
            amount, category, note, expense_date, created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        amount,
        category,
        note,
        expense_date,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    spent = get_category_spending(category)
    limit = get_category_budget(category)

    budget_warning = None

    if limit is not None and spent > limit:
        currency = get_currency()


        budget_warning = (
            f"⚠️ You have crossed your {category} budget. "
            f"Spent {currency} {spent:,.0f} of {currency} {limit:,.0f}."
        )

    return {
        "spent": spent,
        "monthly_limit": limit,
        "remaining_category_budget": (
            limit - spent if limit is not None else None
        ),
        "budget_warning": budget_warning
    }

def get_currency():
    conn = get_db()

    row = conn.execute("""
        SELECT currency
        FROM user_settings
        WHERE id = 1
    """).fetchone()

    conn.close()

    return row["currency"] if row else "INR"


def set_currency(currency):
    conn = get_db()

    conn.execute("""
        UPDATE user_settings
        SET currency = ?
        WHERE id = 1
    """, (currency,))

    conn.commit()
    conn.close()

def add_income(amount, source, income_date):
    conn = get_db()

    conn.execute("""
        INSERT INTO incomes (
            amount, source, income_date, created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        amount,
        source,
        income_date,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def get_month_income(reference=None):
    start = month_start(reference).isoformat()

    conn = get_db()

    rows = conn.execute("""
        SELECT amount, source, income_date
        FROM incomes
        WHERE income_date >= ?
        AND income_date < ?
        ORDER BY income_date DESC
    """, (
    start,
    next_month_start().isoformat()
)).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def set_category_budget(category, amount):
    conn = get_db()

    conn.execute("""
        INSERT INTO category_budgets (category, monthly_limit)
        VALUES (?, ?)
        ON CONFLICT(category) DO UPDATE SET
            monthly_limit = excluded.monthly_limit
    """, (category, amount))

    conn.commit()
    conn.close()


def get_category_budget(category):
    conn = get_db()

    row = conn.execute("""
        SELECT monthly_limit
        FROM category_budgets
        WHERE category = ?
    """, (category,)).fetchone()

    conn.close()

    if row:
        return row["monthly_limit"]

    return None


def get_category_spending(category):
    monthly_expenses = get_month_expenses()

    return sum(
        expense["amount"]
        for expense in monthly_expenses
        if expense["category"] == category
    )


def get_expenses_by_date(expense_date):
    conn = get_db()

    rows = conn.execute("""
        SELECT amount, category, note, expense_date
        FROM expenses
        WHERE expense_date = ?
        ORDER BY created_at ASC
    """, (expense_date,)).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def find_expense_by_note(search_text):
    conn = get_db()

    rows = conn.execute("""
        SELECT amount, category, note, expense_date
        FROM expenses
        WHERE LOWER(note) LIKE ?
        ORDER BY expense_date DESC
    """, (f"%{search_text.lower()}%",)).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_month_expenses(reference=None):
    start = month_start(reference).isoformat()

    conn = get_db()

    rows = conn.execute("""
        SELECT amount, category, note, expense_date
        FROM expenses
        WHERE expense_date >= ?
        AND expense_date < ?
        ORDER BY expense_date DESC
    """, (
    start,
    next_month_start().isoformat()
)).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_recent_expenses(limit=10):
    conn = get_db()

    rows = conn.execute("""
        SELECT amount, category, note, expense_date
        FROM expenses
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_remaining_balance():
    monthly_expenses = get_month_expenses()
    monthly_incomes = get_month_income()

    total_spent = sum(
        expense["amount"] for expense in monthly_expenses
    )

    total_income = sum(
        income["amount"] for income in monthly_incomes
    )

    return get_budget() + total_income - total_spent


def parse_date(text):
    text = str(text).lower().strip()

    if "today" in text:
        return date.today().isoformat()

    if "yesterday" in text:
        return (date.today() - timedelta(days=1)).isoformat()

    date_formats = [
        "%d/%m/%y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y"
    ]

    for date_format in date_formats:
        try:
            parsed = datetime.strptime(text, date_format)
            return parsed.date().isoformat()
        except ValueError:
            continue

    raise ValueError(
    "Please provide a clear date, such as today, yesterday, "
    "or DD/MM/YYYY."
)


def get_budget_status():
    monthly_expenses = get_month_expenses()
    monthly_incomes = get_month_income()

    total_spent = sum(
        expense["amount"] for expense in monthly_expenses
    )

    total_income = sum(
        income["amount"] for income in monthly_incomes
    )

    remaining = get_remaining_balance()

    today = date.today()
    start = month_start(today)
    month_end = next_month_start(today)

    days_used = max((today - start).days + 1, 1)
    days_left = max((month_end - today).days, 1)
    days_in_month = max((month_end - start).days, 1)

    daily_limit = round(max(remaining / days_left, 0), 2)

    average_daily_spend = total_spent / days_used
    projected_spend = total_spent + (average_daily_spend * days_left)
    projected_end_balance = get_budget() + total_income - projected_spend

    return {
        "monthly_budget": get_budget(),
        "total_income": total_income,
        "total_spent": total_spent,
        "remaining_balance": remaining,
        "days_used": days_used,
        "days_left": days_left,
        "safe_daily_spend": daily_limit,
        "average_daily_spend": round(average_daily_spend, 2),
        "projected_month_end_spend": round(projected_spend, 2),
        "projected_month_end_balance": round(projected_end_balance, 2),
        "expenses": monthly_expenses
    }


def get_spending_insights():
    monthly_expenses = get_month_expenses()

    category_totals = {}

    for expense in monthly_expenses:
        category = expense["category"]
        category_totals[category] = (
            category_totals.get(category, 0) + expense["amount"]
        )

    sorted_categories = sorted(
        category_totals.items(),
        key=lambda item: item[1],
        reverse=True
    )

    total_spent = sum(category_totals.values())

    top_categories = [
        {
            "category": category,
            "amount": amount,
            "percentage": (
                round((amount / total_spent) * 100, 1)
                if total_spent else 0
            )
        }
        for category, amount in sorted_categories[:5]
    ]

    return {
        "total_spent": total_spent,
        "top_categories": top_categories,
        "advice": (
            "Focus on your largest category first. "
            "Set a weekly limit and avoid non-essential purchases."
        )
    }


def set_savings_goal(name, target_amount, target_date):
    conn = get_db()

    conn.execute("""
        INSERT INTO savings_goals (
            name, target_amount, saved_amount, target_date, created_at
        )
        VALUES (?, ?, 0, ?, ?)
    """, (
        name,
        target_amount,
        target_date,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def add_savings_contribution(goal_name, amount):
    conn = get_db()

    row = conn.execute("""
        SELECT id, saved_amount, target_amount
        FROM savings_goals
        WHERE LOWER(name) LIKE ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (f"%{goal_name.lower()}%",)).fetchone()

    if not row:
        conn.close()
        return {"error": "Savings goal not found"}

    new_saved = row["saved_amount"] + amount

    conn.execute("""
        UPDATE savings_goals
        SET saved_amount = ?
        WHERE id = ?
    """, (new_saved, row["id"]))

    conn.commit()
    conn.close()

    return {
        "goal": goal_name,
        "saved_amount": new_saved,
        "remaining": max(row["target_amount"] - new_saved, 0)
    }


def get_savings_goals():
    conn = get_db()

    rows = conn.execute("""
        SELECT name, target_amount, saved_amount, target_date
        FROM savings_goals
        ORDER BY created_at DESC
    """).fetchall()

    conn.close()

    goals = []

    for row in rows:
        goals.append({
            "name": row["name"],
            "target_amount": row["target_amount"],
            "saved_amount": row["saved_amount"],
            "remaining": max(
                row["target_amount"] - row["saved_amount"], 0
            ),
            "target_date": row["target_date"]
        })

    return goals


def add_bill_reminder(name, amount, due_date):
    conn = get_db()

    conn.execute("""
        INSERT INTO bills (
            name, amount, due_date, created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        name,
        amount,
        due_date,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def get_upcoming_bills(days=30):
    today = date.today()
    limit_date = today + timedelta(days=days)

    conn = get_db()

    rows = conn.execute("""
        SELECT name, amount, due_date
        FROM bills
        WHERE due_date >= ?
        AND due_date <= ?
        ORDER BY due_date ASC
    """, (today.isoformat(), limit_date.isoformat())).fetchall()

    conn.close()

    bills = []

    for row in rows:
        due_date = date.fromisoformat(row["due_date"])
        days_until = (due_date - today).days

        bills.append({
            "name": row["name"],
            "amount": row["amount"],
            "due_date": row["due_date"],
            "days_until": days_until
        })

    return bills


def delete_last_expense():
    conn = get_db()

    row = conn.execute("""
        SELECT id, amount, category, note, expense_date
        FROM expenses
        ORDER BY created_at DESC
        LIMIT 1
    """).fetchone()

    if not row:
        conn.close()
        return {"error": "No expenses found"}

    conn.execute(
        "DELETE FROM expenses WHERE id = ?",
        (row["id"],)
    )

    conn.commit()
    conn.close()

    return {
        "deleted": True,
        "expense": dict(row),
        "remaining_balance": get_remaining_balance()
    }


def update_last_expense(category=None, amount=None):
    conn = get_db()

    row = conn.execute("""
        SELECT id
        FROM expenses
        ORDER BY created_at DESC
        LIMIT 1
    """).fetchone()

    if not row:
        conn.close()
        return {"error": "No expenses found"}

    if category:
        conn.execute(
            "UPDATE expenses SET category = ? WHERE id = ?",
            (category, row["id"])
        )

    if amount is not None:
        conn.execute(
            "UPDATE expenses SET amount = ? WHERE id = ?",
            (float(amount), row["id"])
        )

    conn.commit()
    conn.close()

    return {
        "updated": True,
        "remaining_balance": get_remaining_balance()
    }


def filter_expenses(category=None, min_amount=None, max_amount=None):
    query = """
        SELECT amount, category, note, expense_date
        FROM expenses
        WHERE 1 = 1
    """

    params = []

    if category:
        query += " AND category = ?"
        params.append(category)

    if min_amount is not None:
        query += " AND amount >= ?"
        params.append(float(min_amount))

    if max_amount is not None:
        query += " AND amount <= ?"
        params.append(float(max_amount))

    query += " ORDER BY expense_date DESC"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_weekly_expenses():
    today = date.today()
    weekly = []

    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_text = day.isoformat()

        conn = get_db()

        row = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE expense_date = ?
        """, (day_text,)).fetchone()

        conn.close()

        weekly.append({
            "date": day_text,
            "day": day.strftime("%a"),
            "total": row["total"]
        })

    return weekly


def get_monthly_trend():
    today = date.today()
    trend = []

    for offset in range(2, -1, -1):
        if today.month - offset <= 0:
            reference = today.replace(
                year=today.year - 1,
                month=today.month - offset + 12,
                day=1
            )
        else:
            reference = today.replace(
                month=today.month - offset,
                day=1
            )

        start = month_start(reference)
        end = next_month_start(reference)

        conn = get_db()

        row = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE expense_date >= ?
            AND expense_date < ?
        """, (
            start.isoformat(),
            end.isoformat()
        )).fetchone()

        conn.close()

        trend.append({
            "month": start.strftime("%b %Y"),
            "total": row["total"]
        })

    return trend

def json_safe(value):
    if isinstance(value, set):
        return list(value)

    if isinstance(value, dict):
        return {
            key: json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            json_safe(item)
            for item in value
        ]

    return value


def run_tool(tool_name, arguments):
    try:
    
        if tool_name == "get_monthly_report":
            return {
                "budget": get_budget_status(),
                "insights": get_spending_insights(),
                "upcoming_bills": get_upcoming_bills(30),
                "savings_goals": get_savings_goals()
            }
        
        if tool_name == "add_expense":
            expense_result = add_expense(
                float(arguments["amount"]),
                arguments["category"],
                arguments["note"],
                parse_date(arguments["date_text"])
            )

            return {
                "success": True,
                "remaining_balance": get_remaining_balance(),
                "category": arguments["category"],
                "category_spent": expense_result["spent"],
                "category_monthly_limit": expense_result["monthly_limit"],
                "category_budget_remaining": expense_result[
                    "remaining_category_budget"
                ],
                "budget_warning": expense_result["budget_warning"]
            }

        if tool_name == "add_income":
            add_income(
                float(arguments["amount"]),
                arguments["source"],
                parse_date(arguments["date_text"])
            )

            return {
                "success": True,
                "remaining_balance": get_remaining_balance()
            }

        if tool_name == "set_budget":
            set_budget(float(arguments["amount"]))

            return {
                "success": True,
                "monthly_budget": get_budget()
            }

        if tool_name == "get_budget":
            return get_budget_status()

        if tool_name == "get_budget_status":
            return get_budget_status()

        if tool_name == "get_spending_insights":
            return get_spending_insights()

        if tool_name == "get_expenses_by_date":
            expense_date = parse_date(arguments["date_text"])

            return {
                "date": expense_date,
                "expenses": get_expenses_by_date(expense_date)
            }

        if tool_name == "find_expense":
            return {
                "matches": find_expense_by_note(arguments["note"])
            }

        if tool_name == "calculate_savings_goal":
            item_price = float(arguments["item_price"])
            remaining = get_remaining_balance()
            amount_needed = max(item_price - remaining, 0)

            return {
                "item": arguments["item"],
                "item_price": item_price,
                "remaining_balance": remaining,
                "amount_needed": amount_needed,
                "daily_saving_needed": amount_needed / 30,
                "weekly_saving_needed": amount_needed / 4,
                "can_afford_now": amount_needed == 0
            }

        if tool_name == "set_savings_goal":
            set_savings_goal(
                arguments["name"],
                float(arguments["target_amount"]),
                parse_date(arguments["target_date"])
            )

            return {
                "success": True,
                "goal": arguments["name"],
                "target_amount": arguments["target_amount"]
            }

        if tool_name == "add_savings_contribution":
            return add_savings_contribution(
                arguments["goal_name"],
                float(arguments["amount"])
            )

        if tool_name == "get_savings_goals":
            return {"goals": get_savings_goals()}

        if tool_name == "add_bill_reminder":
            add_bill_reminder(
                arguments["name"],
                float(arguments["amount"]),
                parse_date(arguments["due_date"])
            )

            return {
                "success": True,
                "bill": arguments["name"],
                "due_date": parse_date(arguments["due_date"])
            }

        if tool_name == "get_upcoming_bills":
            return {
                "bills": get_upcoming_bills(
                    int(arguments.get("days", 30))
                )
            }

        if tool_name == "set_category_budget":
            set_category_budget(
                arguments["category"],
                float(arguments["amount"])
            )

            return {
                "success": True,
                "category": arguments["category"],
                "monthly_limit": arguments["amount"]
            }

        if tool_name == "get_category_spending":
            category = arguments["category"]
            spent = get_category_spending(category)
            limit = get_category_budget(category)

            return {
                "category": category,
                "spent": spent,
                "monthly_limit": limit,
                "remaining": (
                    limit - spent if limit is not None else None
                )
            }

        if tool_name == "delete_last_expense":
            return delete_last_expense()

        if tool_name == "update_last_expense":
            return update_last_expense(
                arguments.get("category"),
                arguments.get("amount")
            )

        if tool_name == "filter_expenses":
            return {
                "expenses": filter_expenses(
                    arguments.get("category"),
                    arguments.get("min_amount"),
                    arguments.get("max_amount")
                )
            }
        if tool_name == "set_currency":
            currency = str(arguments["currency"]).upper().strip()

            set_currency(currency)

            return {
                "success": True,
                "currency": currency
            }
            
        return {"error": "Unknown tool"}

    except Exception as error:
        return {"error": str(error)}


def ask_asi_one(message):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    currency = get_currency()

    system_prompt = f"""
You are CashGuard, a premium AI budget agent for students.
The student’s selected currency is {currency}.
Use this currency naturally in replies.

Today is {today}.
Yesterday was {yesterday}.

Your job is to help students manage money naturally.

You can:
- Add expenses
- Add income
- Set a monthly budget
- Check expenses for a date
- Find when an item was purchased
- Show budget status and projections
- Show spending insights
- Calculate savings goals
- Set savings goals
- Add savings contributions
- Add bill reminders
- Show upcoming bills
- Set category budgets
- Check category spending
- Delete or update the latest expense
- Filter expenses by category or amount
- Give practical spending advice

Use the conversation history to understand pronouns and follow-up questions.

Examples:
“I spent 150 on food today” → add_expense
“I got 1500 as a gift yesterday” → add_income
“My monthly budget is 1500 and I spent 700 on rent” → set_budget, then add_expense
“Can I afford a 3000 phone?” → calculate_savings_goal
“I want to buy a 5000 phone. How much should I save?” → calculate_savings_goal
“I want to save 2000 by next month” → set_savings_goal
“I saved 500 towards my phone” → add_savings_contribution
“Remind me to pay WiFi on 5/12/26” → add_bill_reminder
“Show my upcoming bills” → get_upcoming_bills
“Where is my money going?” → get_spending_insights
“How am I doing this month?” → get_budget_status
“Delete my last expense” → delete_last_expense
“Change my last food expense to 200” → update_last_expense
“Show all food expenses” → filter_expenses
“Show expenses above 500” → filter_expenses
“Set my food budget to 3000” → set_category_budget
“How much have I spent on food?” → get_category_spending
“Give me my monthly report” → get_monthly_report
“Change my currency to USD” → set_currency
“Use euros” → set_currency
“Use rupees” → set_currency
“Change my currency to USD” → set_currency with USD
“Use dollars” → set_currency with USD
“Use euros” → set_currency with EUR
“Use rupees” → set_currency with INR
“Change my currency to Japanese Yen” → set_currency with JPY
“Use pounds” → set_currency with GBP
“Use dirhams” → set_currency with AED

Rules:
- Never invent expenses, income, dates, or items.
- Use tools for every financial action.
- If information is missing, ask one short clarifying question.
- Be concise, friendly, professional, and non-judgmental.
- Use the user’s selected currency naturally.
- Do not give investment, loan, crypto, tax, or legal advice.
- After using a tool, explain the result simply.
- If a category budget exists and an expense crosses it, warn the student.
- Use minimal Markdown. Use bold only for very important warnings or totals.
- Do not overuse headings, bullet points, or emojis.

Currency:
- Support every active ISO 4217 currency.
- When the user asks to change currency, identify the correct three-letter ISO currency code.
- “Change my currency to USD” → set_currency
- “Use dollars” → set_currency
- “Use euros” → set_currency
- “Change my currency to INR” → set_currency
- “Use rupees” → set_currency
- “Change my currency to EUR” → set_currency
- “Use euros” → set_currency
- “Change my currency to GBP” → set_currency
- “Use pounds” → set_currency
- “Change my currency to AED” → set_currency
- “Use dirhams” → set_currency

- Use the student’s selected currency symbol in replies.
- Do not convert old expenses unless the student explicitly asks for conversion.
- If the student asks to convert an amount, ask for or identify both the original currency and target currency.
- If the student changes currency, confirm the new currency and explain that future expenses will use it.
- Save only the ISO currency code, such as USD, EUR, INR, JPY, GBP, or AED.
- Do not convert old expenses unless the user explicitly asks for conversion.
- Use the selected currency code and its correct symbol when discussing amounts.
"""

    tools = [
        
        {
            "type":"function",
            "function": {
                "name": "set_currency",
                "description": (
                    "Change the stuednt's preferred display using "
                    "an ISO 4217 currency code"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string"}
                    },
                    "required": ["currency"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_monthly_report",
                "description": (
                    "Get a complete monthly financial report including spending, "
                    "insights, projection, and advice."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        
        {
            "type": "function",
            "function": {
                "name": "add_expense",
                "description": "Add an expense for the student.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "category": {
                            "type": "string",
                            "enum": CATEGORIES
                        },
                        "note": {"type": "string"},
                        "date_text": {"type": "string"}
                    },
                    "required": [
                        "amount",
                        "category",
                        "note",
                        "date_text"
                    ]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "add_income",
                "description": "Add money received by the student.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "source": {"type": "string"},
                        "date_text": {"type": "string"}
                    },
                    "required": [
                        "amount",
                        "source",
                        "date_text"
                    ]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_budget",
                "description": "Set the student’s monthly budget.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"}
                    },
                    "required": ["amount"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_budget",
                "description": (
                    "Get current budget, income, expenses, remaining "
                    "balance, daily limit, pace, and projection."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_budget_status",
                "description": (
                    "Get detailed budget status, spending pace, and "
                    "month-end projection."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_spending_insights",
                "description": (
                    "Get top spending categories and practical advice."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_expenses_by_date",
                "description": "Get expenses for a specific date.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date_text": {"type": "string"}
                    },
                    "required": ["date_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_expense",
                "description": "Find when an item was purchased.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {"type": "string"}
                    },
                    "required": ["note"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculate_savings_goal",
                "description": (
                    "Calculate how much more money is needed to buy an "
                    "item and how much to save."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "item_price": {"type": "number"}
                    },
                    "required": ["item", "item_price"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_savings_goal",
                "description": (
                    "Create a savings goal with a target amount and date."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "target_amount": {"type": "number"},
                        "target_date": {"type": "string"}
                    },
                    "required": [
                        "name",
                        "target_amount",
                        "target_date"
                    ]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "add_savings_contribution",
                "description": (
                    "Add money saved towards a savings goal."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal_name": {"type": "string"},
                        "amount": {"type": "number"}
                    },
                    "required": [
                        "goal_name",
                        "amount"
                    ]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_savings_goals",
                "description": "Get all savings goals and progress.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "add_bill_reminder",
                "description": (
                    "Create a reminder for an upcoming bill."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": "number"},
                        "due_date": {"type": "string"}
                    },
                    "required": [
                        "name",
                        "amount",
                        "due_date"
                    ]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_upcoming_bills",
                "description": "Get upcoming bill reminders.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "number"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_category_budget",
                "description": (
                    "Set a monthly spending limit for a category."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": CATEGORIES
                        },
                        "amount": {"type": "number"}
                    },
                    "required": [
                        "category",
                        "amount"
                    ]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_category_spending",
                "description": (
                    "Get how much the student has spent in one category "
                    "this month."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": CATEGORIES
                        }
                    },
                    "required": ["category"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_last_expense",
                "description": "Delete the most recent expense.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_last_expense",
                "description": (
                    "Update the category or amount of the most recent "
                    "expense."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": CATEGORIES
                        },
                        "amount": {"type": "number"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "filter_expenses",
                "description": (
                    "Filter expenses by category, minimum amount, or "
                    "maximum amount."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": CATEGORIES
                        },
                        "min_amount": {"type": "number"},
                        "max_amount": {"type": "number"}
                    },
                    "required": []
                }
            }
        }
    ]

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)
    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model="asi1",
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0
    )

    message_data = response.choices[0].message

    if not message_data.tool_calls:
        reply = message_data.content or (
            "I can help you track expenses, add income, check your "
            "budget, plan savings, manage bills, or show insights."
        )

        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": reply})
        chat_history[:] = chat_history[-10:]

        return reply

    messages.append(
        message_data.model_dump(exclude_none=True)
    )

    for tool_call in message_data.tool_calls:
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        result = run_tool(tool_name, arguments)

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, default=str)
        })

    final_response = client.chat.completions.create(
        model="asi1",
        messages=messages,
        temperature=0
    )

    reply = final_response.choices[0].message.content

    chat_history.append({"role": "user", "content": message})
    chat_history.append({"role": "assistant", "content": reply})
    chat_history[:] = chat_history[-10:]

    return reply


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
def chat(request: ChatRequest):
    try:
        reply = ask_asi_one(request.message)
        currency = get_currency()

        return {
            "reply": reply,
            "currency": currency
        }

    except Exception as error:
        import traceback

        full_error = traceback.format_exc()

        print(full_error)

        return {
            "reply": (
                "Sorry, I had trouble understanding that. "
                "Please try again."
            ),
            "currency": get_currency()
        }

@app.post("/agent-chat")
async def agent_chat(envelope: Envelope):
    try:
        message = envelope.parse_content()

        user_text = ""

        if isinstance(message, ChatMessage):
            for content in message.content:
                if isinstance(content, TextContent):
                    user_text += content.text

        reply = ask_asi_one(user_text)

        response_message = ChatMessage(
            timestamp=datetime.now(),
            msg_id=str(uuid.uuid4()),
            content=[TextContent(type="text", text=reply)],
        )

        send_message_to_agent(
            destination=envelope.sender,
            msg=response_message,
            sender=identity,
        )

        return {"status": "ok"}


    except Exception:
        import traceback
        print(traceback.format_exc())

        fallback_message = ChatMessage(
            timestamp=datetime.now(),
            msg_id=str(uuid.uuid4()),
            content=[
                TextContent(
                    type="text",
                    text="Sorry, I had trouble understanding that. Please try again.",
                )
            ],
        )

        return {"status": "error"}

from typing import cast
from uagents_core.utils.messages import parse_envelope, send_message_to_agent
from uagents_core.identity import Identity

identity = Identity.from_seed(os.getenv("AGENT_SEED_PHRASE"), 0)


@app.post("/")
async def agentverse_chat(envelope: Envelope):
    try:
        message = cast(ChatMessage, parse_envelope(envelope, ChatMessage))

        if isinstance(message, ChatMessage):
            user_text = ""

            for content in message.content:
                if isinstance(content, TextContent):
                    user_text += content.text
        else:
            user_text = str(message)

        reply = ask_asi_one(user_text)

        response_message = ChatMessage(
            timestamp=datetime.now(),
            msg_id=str(uuid.uuid4()),
            content=[TextContent(type="text", text=reply)],
        )

        return Envelope(
            version=envelope.version,
            sender=envelope.target,
            target=envelope.sender,
            session=envelope.session,
            schema_digest=envelope.schema_digest,
            content=response_message,
        )

    except Exception:
        import traceback
        print(traceback.format_exc())

        fallback_message = ChatMessage(
            timestamp=datetime.now(),
            msg_id=str(uuid.uuid4()),
            content=[
                TextContent(
                    type="text",
                    text="Sorry, I had trouble understanding that. Please try again.",
                )
            ],
        )

        return Envelope(
            version=envelope.version,
            sender=envelope.target,
            target=envelope.sender,
            session=envelope.session,
            schema_digest=envelope.schema_digest,
            content=fallback_message,
        )

@app.get("/dashboard")
def dashboard():
    return {
        "currency": get_currency(),
        "budget": get_budget_status(),
        "insights": get_spending_insights(),
        "recent": get_recent_expenses(10),
        "weekly": get_weekly_expenses(),
        "trend": get_monthly_trend(),
        "bills": get_upcoming_bills(30),
        "goals": get_savings_goals()
    }


@app.get("/export/csv")
def export_csv():
    conn = get_db()

    rows = conn.execute("""
        SELECT amount, category, note, expense_date, created_at
        FROM expenses
        ORDER BY expense_date DESC
    """).fetchall()

    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Amount",
        "Category",
        "Note",
        "Date",
        "Created At"
    ])

    for row in rows:
        writer.writerow([
            row["amount"],
            row["category"],
            row["note"],
            row["expense_date"],
            row["created_at"]
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                "attachment; filename=cashguard-expenses.csv"
            )
        }
    )


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
      <head>
        <title>CashGuard</title>
        <meta name="color-scheme" content="light dark">
        <style>
          * { box-sizing: border-box; }
          body {
            margin: 0;
            font-family: Inter, Arial, sans-serif;
            background: #f6f7fb;
            color: #111827;
          }
          body.dark {
            background: #0f172a;
            color: #e2e8f0;
          }
          .app {
            max-width: 900px;
            margin: auto;
            height: 100vh;
            display: flex;
            flex-direction: column;
          }
          header {
            padding: 16px 24px;
            background: white;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            align-items: center;
            gap: 12px;
          }
          body.dark header {
            background: #1e293b;
            border-color: #334155;
          }
          .logo {
            width: 38px;
            height: 38px;
            border-radius: 12px;
            background: #4f46e5;
            color: white;
            display: grid;
            place-items: center;
            font-weight: 700;
          }
          h1 { font-size: 18px; margin: 0; }
          p { margin: 2px 0 0; color: #6b7280; font-size: 13px; }
          .tabs {
            display: flex;
            gap: 8px;
            margin-left: auto;
          }
          .tab {
            padding: 8px 14px;
            border-radius: 10px;
            border: 1px solid #d1d5db;
            background: white;
            cursor: pointer;
            font-size: 13px;
          }
          body.dark .tab {
            background: #334155;
            border-color: #475569;
            color: #e2e8f0;
          }
          .tab.active {
            background: #4f46e5;
            color: white;
            border-color: #4f46e5;
          }
          main {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
          }
          .view {
            display: none;
          }
          .view.active {
            display: block;
          }
          #chat {
            display: flex;
            flex-direction: column;
            gap: 14px;
            min-height: 100%;
          }
          .message {
            max-width: 78%;
            padding: 13px 16px;
            border-radius: 16px;
            line-height: 1.55;
            white-space: pre-wrap;
          }
          .user {
            align-self: flex-end;
            background: #4f46e5;
            color: white;
            border-bottom-right-radius: 5px;
          }
          .agent {
            align-self: flex-start;
            background: white;
            border: 1px solid #e5e7eb;
            border-bottom-left-radius: 5px;
          }
          body.dark .agent {
            background: #1e293b;
            border-color: #334155;
          }
          form {
            display: flex;
            gap: 10px;
            padding: 16px;
            background: white;
            border-top: 1px solid #e5e7eb;
          }
          body.dark form {
            background: #1e293b;
            border-color: #334155;
          }
          input {
            flex: 1;
            padding: 14px;
            border-radius: 12px;
            border: 1px solid #d1d5db;
            font-size: 15px;
          }
          button {
            padding: 14px 22px;
            border: none;
            border-radius: 12px;
            background: #4f46e5;
            color: white;
            font-weight: 600;
            cursor: pointer;
          }
          .card {
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 16px;
            padding: 18px;
            margin-bottom: 16px;
          }
          body.dark .card {
            background: #1e293b;
            border-color: #334155;
          }
          .progress {
            height: 12px;
            background: #e5e7eb;
            border-radius: 999px;
            overflow: hidden;
            margin-top: 10px;
          }
          .progress-fill {
            height: 100%;
            background: #4f46e5;
          }
          .bar {
            height: 10px;
            background: #e5e7eb;
            border-radius: 999px;
            overflow: hidden;
            margin: 6px 0 12px;
          }
          .bar-fill {
            height: 100%;
            background: #22c55e;
          }
          .small {
            font-size: 13px;
            color: #6b7280;
          }
          body.dark .small {
            color: #94a3b8;
          }
          .transaction {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #f1f5f9;
          }
          body.dark .transaction {
            border-color: #334155;
          }
          .weekly {
            display: flex;
            align-items: flex-end;
            gap: 10px;
            height: 140px;
          }
          .weekly-column {
            flex: 1;
            text-align: center;
          }
          .weekly-bar {
            background: #4f46e5;
            border-radius: 6px 6px 0 0;
            width: 100%;
          }
          
          header h1,
          header p,
          .tab {
            color: #111827;
          }

          .tab.active {
            color: #ffffff;
          }

          .message.agent {
            color: #111827;
          }

          .message.user {
            color: #ffffff;
          }

          body.dark header h1,
          body.dark header p,
          body.dark .tab {
            color: #e2e8f0;
          }

          body.dark .tab.active {
            color: #ffffff;
          }

          body.dark .message.agent {
            color: #e2e8f0;
          }

          body.dark .message.user {
            color: #ffffff;
          }              
        </style>
      </head>
      <body>
        <div class="app">
          <header>
            <div class="logo" id="currency-logo">₹</div>
            <div>
              <h1>CashGuard</h1>
              <p>Your AI budget agent</p>
            </div>

            <div class="tabs">
              <button class="tab active" onclick="showView('chat')">
                Chat
              </button>
              <button class="tab" onclick="showView('dashboard')">
                Dashboard
              </button>
              <button class="tab" onclick="toggleDarkMode()">
                Dark
              </button>
            </div>
          </header>

          <main>
            <div id="chat-view" class="view active">
              <div id="chat">
                <div class="message agent">
                  Hi! I’m CashGuard. Tell me things like:<br><br>
                  • I spent 150 on food today<br>
                  • I got 1500 as a gift yesterday<br>
                  • Where is my money going?<br>
                  • How am I doing this month?<br>
                  • I want to save 2000 by next month<br>
                  • Remind me to pay WiFi on 5/12/26<br>
                  • Delete my last expense<br>
                  • Show all food expenses<br>
                  • Show expenses above 500
                </div>
              </div>
            </div>

            <div id="dashboard-view" class="view">
              <div id="dashboard"></div>
            </div>
          </main>

          <form onsubmit="sendMessage(event)">
            <input
              id="message"
              placeholder="Tell CashGuard what you spent, earned, or want to buy…"
              autocomplete="off"
              required
            >
            <button type="submit">Send</button>
          </form>
        </div>

        <script>
        
        const currencySymbols = {
            INR: "₹",
            USD: "$",
            EUR: "€",
            GBP: "£",
            AED: "د.إ",
            SGD: "S$",
            AUD: "A$",
            CAD: "C$"
        };
        
        function esc(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function updateCurrencyLogo(currency) {
  const logo = document.getElementById("currency-logo");
  const selectedCurrency = currency || "INR";

  logo.textContent = selectedCurrency;
}
          async function sendMessage(event) {
            event.preventDefault();

            const input = document.getElementById("message");
            const text = input.value;
            input.value = "";

            addMessage(text, "user");
            addMessage("Thinking…", "agent", true);

            try {
              const response = await fetch("/chat", {
                method: "POST",
                headers: {
                  "Content-Type": "application/json"
                },
                body: JSON.stringify({ message: text })
              });

              const data = await response.json();

              removeThinking();
              
              if (data.currency) {
                  updateCurrencyLogo(data.currency);
              }
              addMessage(
                  data.reply || "Sorry, I could not get a response.",
                  "agent"
              )

            } catch (error) {
              removeThinking();
              addMessage(
                "Sorry, I could not connect to CashGuard.",
                "agent"
              );
            }
          }

          function removeThinking() {
            const thinking = document.getElementById("thinking");

            if (thinking) {
              thinking.remove();
            }
          }

          function addMessage(text, type, thinking = false) {
            const chat = document.getElementById("chat");
            const div = document.createElement("div");

            div.className = "message " + type;

            if (thinking) {
              div.id = "thinking";
            }

            div.innerText = text;

            chat.appendChild(div);
            document.querySelector("main").scrollTop =
                document.querySelector("main").scrollHeight;
          }

          function showView(view) {
            const chatView = document.getElementById("chat-view");
            const dashboardView = document.getElementById(
              "dashboard-view"
            );

            const buttons = document.querySelectorAll(".tab");

            if (view === "chat") {
              chatView.classList.add("active");
              dashboardView.classList.remove("active");
              buttons[0].classList.add("active");
              buttons[1].classList.remove("active");
            } else {
              chatView.classList.remove("active");
              dashboardView.classList.add("active");
              buttons[0].classList.remove("active");
              buttons[1].classList.add("active");
              loadDashboard();
            }
          }

          function toggleDarkMode() {
  const body = document.body;
  body.classList.toggle("dark");

  const isDark = body.classList.contains("dark");
  localStorage.setItem("cashguard-theme", isDark ? "dark" : "light");
}

function applySavedTheme() {
  const savedTheme = localStorage.getItem("cashguard-theme");

  if (savedTheme === "dark") {
    document.body.classList.add("dark");
    return;
  }

  if (savedTheme === "light") {
    document.body.classList.remove("dark");
    return;
  }

  const prefersDark = window.matchMedia(
    "(prefers-color-scheme: dark)"
  ).matches;

  if (prefersDark) {
    document.body.classList.add("dark");
  }
}

applySavedTheme();

          async function loadDashboard() {
            const dashboard = document.getElementById("dashboard");

            dashboard.innerHTML = "Loading dashboard…";

            try {
              const response = await fetch("/dashboard");
              const data = await response.json();

              const budget = data.budget;
              const insights = data.insights;
              const weekly = data.weekly;
              const trend = data.trend;
              const currency = data.currency || "INR";


              function formatMoney(amount) {
                return new Intl.NumberFormat("en-IN", {
                    style: "currency",
                    currency: currency
                }).format(amount);
              }

              const spentPercent = budget.monthly_budget
                ? Math.min(
                    (budget.total_spent / budget.monthly_budget) * 100,
                    100
                  )
                : 0;

              const maxWeekly = Math.max(
                ...weekly.map(day => day.total),
                1
              );

              dashboard.innerHTML = `
                <div class="card">
                  <h3>Budget</h3>
                  <div class="small">
                    Spent ${formatMoney(budget.total_spent)} of
                    ${formatMoney(budget.monthly_budget)}
                  </div>
                  <div class="progress">
                    <div
                      class="progress-fill"
                      style="width: ${spentPercent}%"
                    ></div>
                  </div>
                  <div class="small">
                    Remaining:  ${formatMoney(budget.remaining_balance)}
                    • Safe daily spend:
                    ${formatMoney(budget.safe_daily_spend)}
                  </div>
                  <div class="small">
                    Projected month-end balance:
                    ${formatMoney(budget.projected_month_end_balance)}
                  </div>
                </div>

                <div class="card">
                  <h3>Where your money is going</h3>
                  ${
                    insights.top_categories.length
                      ? insights.top_categories.map(item => `
                          <div class="small">
                            ${item.category}: ${formatMoney(item.amount)}
                            (${item.percentage}%)
                          </div>
                          <div class="bar">
                            <div
                              class="bar-fill"
                              style="width: ${item.percentage}%"
                            ></div>
                          </div>
                        `).join("")
                      : "<div class='small'>No expenses yet.</div>"
                  }
                </div>

                <div class="card">
                  <h3>This week</h3>
                  <div class="weekly">
                    ${
                      weekly.map(day => `
                        <div class="weekly-column">
                          <div
                            class="weekly-bar"
                            style="height: ${
                              (day.total / maxWeekly) * 120
                            }px"
                          ></div>
                          <div class="small">${day.day}</div>
                        </div>
                      `).join("")
                    }
                  </div>
                </div>

                <div class="card">
                  <h3>Monthly trend</h3>
                  ${
                    trend.map(month => `
                      <div class="small">
                        ${month.month}:
                        ${formatMoney(month.total)}
                      </div>
                    `).join("")
                  }
                </div>

                <div class="card">
                  <h3>Recent expenses</h3>
                  ${
                    data.recent.length
                      ? data.recent.map(item => `
                          <div class="transaction">
                            <div>
                              <div>${esc(item.note)}</div>
                              <div class="small">
                                ${esc(item.category)} • ${item.expense_date}
                              </div>
                            </div>
                            <div>
                              ₹${formatMoney(item.amount)}
                            </div>
                          </div>
                        `).join("")
                      : "<div class='small'>No expenses yet.</div>"
                  }
                </div>

                <div class="card">
                  <h3>Bills and goals</h3>
                  <div class="small">
                    Upcoming bills: ${data.bills.length}
                  </div>
                  <div class="small">
                    Savings goals: ${data.goals.length}
                  </div>
                  <button onclick="window.location='/export/csv'">
                    Download expenses CSV
                  </button>
                </div>
              `;

            } catch (error) {
              dashboard.innerHTML =
                "Could not load dashboard. Please try again.";
            }
          }
          
        window.addEventListener("DOMContentLoaded", async () => {
            try {
                const response = await fetch("/dashboard");
                const data = await response.json();
                
                const currency = data.currency || "INR";

function formatMoney(amount) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: currency
  }).format(amount);
}

                updateCurrencyLogo(data.currency || "INR");
            } catch (error) {
              updateCurrencyLogo("INR");
            }
        });
          
        </script>
      </body>
    </html>
    """
