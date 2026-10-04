# Discord Ticket Bot

A functional Discord ticket bot built with discord.py.

Features:
- Ticket creation by category and priority
- Support panel with category buttons
- Ticket close / resolve commands
- Transcript logging to a Discord channel
- Custom fields via ticket subject and details
- Metadata stored in the Discord channel topic

## Setup

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   ```

4. Run the bot:
   ```bash
   python bot.py
   ```

## Commands

- `/ticket new` - Create a new ticket
- `/ticket panel` - Send a support panel into the current channel
- `/ticket close` - Close the current ticket
- `/ticket resolve` - Resolve the current ticket

## Notes

This implementation stores ticket data in the Discord channel topic as JSON and saves logs to a channel named `ticket-logs`.
