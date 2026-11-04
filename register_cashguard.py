import os
from dotenv import load_dotenv
from uagents_core.utils.registration import (
    register_chat_agent,
    RegistrationRequestCredentials,
)

load_dotenv()

print("AGENTVERSE_KEY found:", "AGENTVERSE_KEY" in os.environ)
print("AGENT_SEED_PHRASE found:", "AGENT_SEED_PHRASE" in os.environ)

register_chat_agent(
    "CashGuard",
    "https://nimbly-wooing-overblown.ngrok-free.dev/",
    active=True,
    credentials=RegistrationRequestCredentials(
        agentverse_api_key=os.environ["AGENTVERSE_KEY"],
        agent_seed_phrase=os.environ["AGENT_SEED_PHRASE"],
    ),
)

print("CashGuard registered with Agentverse.")