from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

budget = 10000
spent = 0

@app.get("/", response_class=HTMLResponse)
def home():
    remaining = budget - spent
    return f"""
    <html>
      <body style="font-family: Arial; padding: 40px;">
        <h1>CashGuard</h1>
        <h2>Money left: ₹{remaining}</h2>

        <form action="/add-expense" method="get">
          <input name="amount" placeholder="Amount spent" type="number">
          <input name="note" placeholder="What did you buy?">
          <button>Add expense</button>
        </form>
      </body>
    </html>
    """

@app.get("/add-expense")
def add_expense(amount: int = 0, note: str = ""):
    global spent
    spent += amount
    remaining = budget - spent
    return f"""
    <html>
      <body style="font-family: Arial; padding: 40px;">
        <h1>Expense added</h1>
        <p>You spent ₹{amount} on {note}.</p>
        <h2>Money left: ₹{remaining}</h2>
        <a href="/">Go back</a>
      </body>
    </html>
    """