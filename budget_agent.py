from uagents import Agent, Context, Model

class BudgetRequest(Model):
    monthly_budget: int
    remaining_budget: int
    days_left: int
    top_category: str
    total_spent: int

class BudgetResponse(Model):
    advice: str

agent = Agent(
    name="cashguard_budget_planner",
    seed="cashguard budget planner secret seed 123",
    port=8001,
    endpoint=["http://localhost:8001/submit"]
)

@agent.on_rest_post("/budget-advice", BudgetRequest, BudgetResponse)
async def budget_advice(ctx: Context, req: BudgetRequest) -> BudgetResponse:
    daily_limit = req.remaining_budget // max(req.days_left, 1)

    if req.remaining_budget <= 0:
        advice = "❌ You have no budget left. Avoid non-essential spending until your next allowance."
    elif daily_limit < 100:
        advice = f"⚠️ You are spending too quickly. Limit yourself to about ₹{daily_limit} per day."
    elif req.top_category:
        advice = f"✅ You can spend about ₹{daily_limit} per day. Your biggest category is {req.top_category}. Reduce spending there if you want to save more."
    else:
        advice = f"✅ You are on track. You can spend about ₹{daily_limit} per day."

    return BudgetResponse(advice=advice)

@agent.on_event("startup")
async def startup(ctx):
    ctx.logger.info(f"Budget Planner Agent started: {agent.address}")

if __name__ == "__main__":
    agent.run()
