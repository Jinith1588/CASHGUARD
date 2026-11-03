from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

budget = 10000
expenses = []

@app.get("/", response_class=HTMLResponse)
def home():
    remaining = budget - sum(expenses)
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

    remaining = budget - sum(expenses)

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
