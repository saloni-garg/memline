"""Context Packs: one click turns the user's approved memory into a brief
shaped for the assistant they are about to use. This is how Memline works
in tools where live connectors are limited (ChatGPT, Gemini) as well as in
tools with full MCP support (Claude, Cursor), where the pack is a snapshot.
"""

KIND_HEADINGS = [
    ("identity", "About me"),
    ("goal", "My current goals"),
    ("principle", "How I decide (my principles)"),
    ("instruction", "How I want you to work"),
    ("preference", "My preferences"),
    ("style", "My writing style"),
    ("project", "My projects"),
    ("narrative", "My story so far"),
    ("person", "People in my life and work"),
    ("fact", "Facts to remember"),
]

WRAPPERS = {
    "chatgpt": (
        "Paste this as your first message (or into Settings > Personalization > Custom instructions):",
        "Here is context about me from my personal memory. Use it for everything we do in this chat, and do not ask me to repeat it.",
    ),
    "claude": (
        "Paste this into a Claude Project's custom instructions, or as your first message:",
        "Here is context about me from my personal memory. Treat it as standing background for this conversation.",
    ),
    "gemini": (
        "Paste this as your first message in Gemini:",
        "Here is context about me from my personal memory. Keep it in mind throughout this conversation.",
    ),
    "cursor": (
        "Save this as .cursorrules in your project, or paste it into Cursor settings > Rules:",
        "# Context about the person you are assisting (from their personal memory). Follow it in all suggestions.",
    ),
    "plain": (
        "Copy and paste this wherever you brief an assistant:",
        "Here is context about me from my personal memory.",
    ),
}


def build_pack(memories: list[dict], target: str = "plain", project: str = "") -> str:
    note, intro = WRAPPERS.get(target, WRAPPERS["plain"])
    lines = [intro, ""]
    by_kind = {}
    for mem in memories:
        by_kind.setdefault(mem["kind"], []).append(mem)
    for kind, heading in KIND_HEADINGS:
        items = by_kind.get(kind)
        if not items:
            continue
        lines.append(f"## {heading}")
        for mem in items:
            label = f"**{mem['title']}:** " if mem["title"] else ""
            proj = f" (project: {mem['project']})" if mem.get("project") else ""
            lines.append(f"- {label}{mem['body']}{proj}")
        lines.append("")
    unknowns = by_kind.get("unknown")
    if unknowns:
        lines.append("## What is not understood about me yet (do not guess these)")
        for mem in unknowns:
            label = f"**{mem['title']}:** " if mem["title"] else ""
            lines.append(f"- {label}{mem['body']}")
        lines.append("")
    if project:
        lines.insert(1, f"Focus: project '{project}'.")
    return note + "\n\n" + "\n".join(lines).strip() + "\n"
