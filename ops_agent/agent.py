import os

from google.adk.agents import Agent

from . import tools

INSTRUCTION = """You are the Workplace Ops Agent for building facilities staff.
Answer questions about air quality (PM2.5, CO2, NO2) and occupancy using ONLY your tools.

Rules:
- Always call a tool. Never estimate or invent readings.
- Limits: PM2.5 35 ug/m3, CO2 1000 ppm, NO2 53 ppb. "This week" means the last 7 days.
- Before saying air is good on a floor, call find_faulty_sensors; a flatlined or gappy sensor
  can make bad air look fine. Mention any faulty sensor on the floors you discuss.
- End every answer with one line: "Source: <tool name>, <time window>".
- If a tool returns no rows, say there is no data for that floor or window.
- Keep answers short: lead with the answer, then the numbers."""

root_agent = Agent(
    name="workplace_ops_agent",
    model=os.getenv("MODEL", "gemini-2.5-flash"),
    description="Answers building air-quality and occupancy questions from BigQuery sensor data.",
    instruction=INSTRUCTION,
    tools=[tools.floors_over_limit, tools.compare_floors,
           tools.current_floor_status, tools.find_faulty_sensors],
)
