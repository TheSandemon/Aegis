# Aegis: Multi-Agent Kanban & Orchestration Hub

Aegis is a Kanban board that manages AI agents like a development team. Think of it as Trello, but your tasks are done by AI agents.

**No complicated setup** - just double-click and go.

## What Does It Do?

- 📋 **Kanban Board** - Drag cards between columns like Trello
- 🤖 **AI Workers** - Assign tasks to AI agents (OpenClaw, Gemini CLI)
- 🔒 **Human Approval** - AI can work freely, but YOU must approve before "Done"
- 📺 **Live View** - Watch agents work in real-time
- 🔄 **Auto-Routing** - New tasks automatically go to available agents

## Quick Start (30 seconds)

### Windows
1. Double-click `setup.bat`
2. Wait for installation to finish
3. Opens automatically in your browser!

### Mac/Linux
1. Open terminal in this folder
2. Run: `chmod +x setup.sh && ./setup.sh`
3. Opens automatically in your browser!

That's it! 🎉

## How to Use

### Creating Tasks
1. Click **"+ New Card"**
2. Give it a title and description
3. Choose which column (Inbox, Planned, etc.)

### Assigning to AI
1. Create a card in "Planned" column
2. Aegis automatically assigns it to an available AI agent
3. Watch it move to "In Progress" and work!

### Moving Cards
- **Drag and drop** between columns
- AI can move cards freely
- **"Review" column is protected** - only YOU can move cards from Review to Done
- This prevents AI from doing something unsafe

### Viewing Agent Work
Click any card to see:
- Full description
- Who it's assigned to
- Live terminal output (when running)

## Default Columns

| Column | Who Can Use |
|--------|-------------|
| Inbox | Anyone |
| Planned | Anyone |
| In Progress | AI agents only |
| Blocked | AI agents only |
| Review | **Humans only** |
| Done | Humans only |

## Configuration

Edit `aegis.config.json` to change:

```json
{
  "columns": ["Inbox", "Planned", "In Progress", "Blocked", "Review", "Done"],
  "polling_rate_ms": 5000,        // How often to check for new tasks
  "max_concurrent_agents": 4,    // How many AI can work at once
  "agents": {
    "architect": {"enabled": true},
    "coder": {"enabled": true}
  }
}
```

## Troubleshooting

**"Python not found"**
- Download from https://python.org
- During install, check "Add Python to PATH"

**Port 8080 in use**
- Edit `main.py` and change `port = 8080` to another number

**AI not starting tasks**
- Check `aegis.config.json` has agents enabled
- Make sure your agent binary (openclaw, gemini) is in your PATH

## Stopping Aegis

Press `Ctrl+C` in the terminal window to stop the server.

---

Built with ❤️ for autonomous development teams.
