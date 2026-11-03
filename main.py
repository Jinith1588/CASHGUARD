from fastapi.responses import HTMLResponse
from fastapi import FastAPI

app = FastAPI()

budget = 10000
expenses = []

@app.get("/", response_class=HTMLResponse)
def home():
    remaining = budget - sum(e["amount"] for e in expenses)
    expense_rows = ""

    for e in expenses:
        expense_rows += f"""
        <tr>
          <td>₹{e['amount']}</td>
          <td>{e['note']}</td>
        </tr>
        """

    if remaining < budget * 0.2:
        warning = "<p style='color:red;'><b>Warning: You are running low on money!</b></p>"
    else:
        warning = ""

    return f"""
    <html>
      <head>
        <title>CashGuard</title>
      </head>
      <body style="font-family: Arial; max-width: 700px; margin: auto; padding: 30px;">
        <h1>💸 CashGuard</h1>
        <p>Your AI budget assistant for students.</p>

        <h2>Monthly budget: ₹{budget}</h2>
        <h2>Money left: ₹{remaining}</h2>
        {warning}

        <h3>Add an expense</h3>
        <form action="/add-expense" method="get">
          <input name="amount" type="number" placeholder="Amount" required>
          <input name="note" placeholder="What did you buy?" required>
          <button>Add expense</button>
        </form>

        <h3>Your expenses</h3>
        <table border="1" cellpadding="8">
          <tr>
            <th>Amount</th>
            <th>Note</th>
          </tr>
          {expense_rows}
        </table>
        <h3>Can I afford this?</h3>
<form action="/afford" method="get">
  <input name="amount" type="number" placeholder="Price" required>
  <input name="item" placeholder="What do you want to buy?" required>
  <button>Check</button>
</form>

        <h3>Change monthly budget</h3>
        <form action="/set-budget" method="get">
          <input name="new_budget" type="number" placeholder="New monthly budget" required>
          <button>Set budget</button>
        </form>
      </body>
    </html>
    """

@app.get("/add-expense", response_class=HTMLResponse)
def add_expense(amount: int, note: str):
    expenses.append({
        "amount": amount,
        "note": note
    })

    remaining = budget - sum(expense["amount"] for expense in expenses)

    return f"""
    <html>
      <body style="font-family: Arial; max-width: 700px; margin: auto; padding: 30px;">
        <h1>✅ Expense added</h1>
        <p>You spent ₹{amount} on {note}.</p>
        <h2>Money left: ₹{remaining}</h2>
        <a href="/">Go back</a>
      </body>
    </html>
    """

@app.get("/set-budget", response_class=HTMLResponse)
def set_budget(new_budget: int):
    global budget
    budget = new_budget

    return f"""



    <html>
      <body style="font-family: Arial; max-width: 700px; margin: auto; padding: 30px;">
        <h1>✅ Budget updated</h1>
        <h2>New monthly budget: ₹{budget}</h2>
        <a href="/">Go back</a>
      </body>
    </html>
    """
    
@app.get("/afford", response_class=HTMLResponse)
def afford(amount: int, item: str):
    remaining = budget - sum(e["amount"] for e in expenses)

    if remaining <= 0:
        answer = "❌ No, you cannot afford this."
        advice = "You have no money left in your monthly budget."
        remaining_after = remaining

    else:
        percent_of_remaining = (amount / remaining) * 100
        remaining_after = remaining - amount

        if amount > remaining:
            answer = "❌ No, you cannot afford this right now."
            advice = "This costs more than the money you have left."
        
        elif percent_of_remaining > 50:
            answer = "⚠️ Not recommended."
            advice = f"This uses {percent_of_remaining:.0f}% of your remaining money. It would leave you with only ₹{remaining_after}."
        
        elif percent_of_remaining > 25:
            answer = "⚠️ Maybe, but be careful."
            advice = f"This uses {percent_of_remaining:.0f}% of your remaining money. After buying it, you will have ₹{remaining_after} left."
        
        else:
            answer = "✅ Yes, you can afford this."
            advice = f"This uses {percent_of_remaining:.0f}% of your remaining money. After buying it, you will have ₹{remaining_after} left."

    return f"""
    <html>
      <body style="font-family: Arial; max-width: 700px; margin: auto; padding: 30px;">
        <h1>CashGuard check</h1>
        <h2>{answer}</h2>
        <p>You want to buy <b>{item}</b> for ₹{amount}.</p>
        <p>Money left now: ₹{remaining}</p>
        <p>This purchase uses: <b>{percent_of_remaining:.0f}%</b> of your remaining money</p>
        <p>Money left after purchase: ₹{remaining_after}</p>
        <p>{advice}</p>
        <a href="/">Go back</a>
      </body>
    </html>
    """
