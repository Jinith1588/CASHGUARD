# CASHGUARD

CashGuard is an AI budget agent that helps students manage their monthly allowance and avoid running out of money before the end of the month.

## Problem

Many students receive a fixed monthly allowance but lose track of spending. They often realize too late that they have overspent on food, transport, shopping, or entertainment.

## Solution

CashGuard lets students:

- Set a monthly budget
- Add expenses manually
- Add expenses using natural language, such as “I spent 250 on food”
- See how much money remains
- Check whether they can afford a purchase
- Receive warnings when a purchase uses too much of their remaining budget

## AI Feature

CashGuard uses ASI:One to understand expense messages and extract:

- Amount
- Category
- Short note

Example:

Input: “I spent 250 on food”

Output:

```json
{
  "amount": 250,
  "category": "food",
  "note": "food"
}
```

## Tech Stack

- Python
- FastAPI
- HTML/CSS
- ASI:One API
- python-dotenv

## How to Run

```bash
pip install fastapi uvicorn openai python-dotenv
uvicorn main:app --reload
```

Then open:

http://127.0.0.1:8000

## Future Features

- Connect to Fetch.ai Agentverse
- Add a Budget Planner uAgent
- Add recurring bill reminders
- Add weekly spending insights
- Support multiple currencies
