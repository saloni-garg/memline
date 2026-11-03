# Memline core architecture v3: the Understanding Engine

Adopted 2026-10-31, revised to v3 on 2026-11-01, with the Evidence layer, the compounding-understanding reframe, and the wedge override added the same day (v3.1). This document supersedes the v1 roadmap framing and the v2 architecture. V1 (live at mindcarry.fly.dev) was a memory system: conversation, extract memories, store memories, retrieve memories. V2 removed "memory" as the central concept. V3 completes the thought:

**Memline builds a living model of you that any AI can understand.**

That is the category: a **user-owned, inspectable, portable user model**. OpenAI, Anthropic, and Google all maintain user models internally, because user models make assistants dramatically better. Theirs are proprietary, tied to one platform, and largely invisible to the user. This architecture is the same idea with the ownership inverted. "Personal memory" is retired as the product's self-description; it describes one artifact among many.

**The litmus test, applied to every decision in this document: does this help the AI remember me, or does it help the AI understand me?**

**The honesty principle, elevated to a headline because it may be the strongest idea in this architecture: missing requirements are first-class output.** The system's signature sentence to any assistant is not "here is what I know". It is **"here is what I know, and here is exactly what I don't."** Very few AI products expose ignorance this cleanly. Every assembly, inference, and profile in this document carries its Unknowns on its face.

## 1. The architecture

```
Observations (conversations, imports, decisions, edits, feedback)
                |
                v
      EVIDENCE LEDGER (immutable, append-only)
                |
                v
      UNDERSTANDING ENGINE
      (extract, infer, challenge, revise)
                |
   +------------+-------------+-------------+------------+
   |            |             |             |            |
 Identity     Facts        Projects       People
 Preferences  Principles    Goals       Writing Style
 Decision Models           Narratives
   |            |             |             |            |
   +------------+-------------+-------------+------------+
        (Skills are not a store. Skills are computed
         from Projects and evidence over the graph.)
                |
                v
      TASK MODEL (requirement-driven)
                |
      Inference over the graph
                |
                v
     Task-specific context, assembled
                |
                v
            Assistant
```

There is no central memory store in this picture. There are typed understanding stores, each with its own shape, update rules, and epistemic status, and underneath all of them sits the substrate the v3 draft still treated as an attachment: evidence.

### Evidence is a first-class layer, not metadata

The full chain is **Observation, then Evidence, then Understanding, then Context**, and the distinction earns its place because of one asymmetry: **evidence is immutable; understanding is not.**

- An **observation** is a raw event: a conversation imported, a decision approved, a draft edited.
- **Evidence** is the distilled, citable residue of observations, kept in an append-only ledger: "edited 17 AI drafts; removed marketing language in 15 of them", each entry pointing back to its observation. Evidence entries are never edited or deleted by the engine. They can be superseded as *support* for a claim, never rewritten as history.
- **Understanding** is the revisable interpretation built on evidence: "prefers understated writing". Understandings change, get challenged, get demoted, and die. When one changes, the evidence underneath does not move, which is exactly what makes the change auditable.
- **Context** is understanding rendered for a task.

Every item in every store below carries references into the ledger, not copies of it. This buys four things the architecture already promised, now with a mechanism instead of a hope: the audit trail under epistemic states (Section 7), the proof paths under inference (Section 3), the evidence shown by a challenge (Section 8), and the answer to the user's most dangerous question, "why do you think that about me", which is always one hop away. It also draws the privacy line cleanly: a user can export or delete their evidence, and every understanding derived from it is listed, because the references run both ways.

### The stores and what makes each one different

The stores are ordered by stability, and stability is load-bearing: the slower a layer changes, the more decisions it silently governs.

- **Identity.** The highest store, and the one v2 missed. Not facts and not goals: who the user takes themselves to be ("I am an engineer", "I am becoming a founder", "I am a parent", "I consider myself a teacher", "research matters more than status"). Identity changes perhaps every few years, slower than principles, far slower than goals or projects. Humans make an enormous number of decisions from identity rather than from principles: the question answered is not "what do I value" but "what would someone like me do". The engine treats Identity as the top filter: task models check identity fit first, the fit check reads it before principles, and a proposed change to Identity is the rarest and most deliberate revision in the system. Identity items are seeded from the starter material and narratives, and confirmed rarely, because stability is their nature.
- **Facts.** Dated, sourced statements (works at Adobe; lives in Santa Clara). Update rule: visible superseding. This is v1, kept.
- **Projects.** Structured objects, not strings: goal, status, collaborators, period, current state. Projects expire and revive; they are the main source of time-scoped context.
- **People.** Entities with relationships and roles that themselves change over time (manager, spouse, collaborator), linked into the graph.
- **Preferences.** Taste and working style (concise over hype, bullets over prose, citations wanted). Increasingly inferred from decisions, always confirmed before they count as Known.
- **Principles.** How the user decides: decision principles, product philosophy, leadership style, risk tolerance, communication philosophy. Captured deliberately (see Section 5) and from decision records. The killer store: authored by a life of choices, not downloadable, not inferable from a weekend of chats.
- **Goals.** Where the user is going (see Section 4). First-class, time-bound, and allowed to change every other store's relevance.
- **Writing Style.** A profile, not a fact: voice, structure habits, banned patterns, exemplars the user approved. Applied as a filter on generated context, not just retrieved.
- **Decision Models.** Recurring choice patterns with their reasoning ("when two options are close, she picks the one with the better downside"), built from decision records over time.
- **Narratives.** Stories that compress thousands of facts (see Section 6).

## 2. Task Models replace the planner

V1 thinking: given a request, find relevant memories (similarity), rank, compress. That is retrieval thinking, and it caps out quickly, because relevance to a task is not similarity to a prompt.

V2 thinking: given a request, **build a task model**: what would someone need to know to do this task well for this person? Then satisfy each requirement from whichever store holds it, and report what could not be satisfied.

Worked example, "help me negotiate an offer":

| Requirement the task creates | Satisfied from |
|---|---|
| Current compensation and its structure | Facts (with date and epistemic status) |
| Target company and role, and what is known about both | Projects, People, graph inference |
| Negotiation philosophy: what she optimizes, what she never trades | Principles |
| Risk tolerance right now | Principles, Goals |
| Financial situation: runway, obligations, walk-away point | Facts, Goals (flagged sensitive, confirmed before export) |
| Previous negotiations and how they went | Decision records, Narratives |
| How she writes and sounds when it matters | Writing Style |

Requirements come from three places: a library of task models for common task families (negotiation, resume, interview prep, writing, coding, travel, purchase decisions, planning), each maintained and improvable; goals, which inject their own requirements into almost every task; and inference, which adds requirements the user did not state (an offer negotiation for a person with an active "become Staff" goal is also a leveling conversation, so staff-level scope evidence becomes a requirement).

Two properties make this the core architecture rather than a feature:
1. **Missing requirements are first-class output.** If walk-away point is Unknown, the system asks, or proceeds and labels the gap. This absorbs the old "predict missing context" idea into the engine instead of bolting it on.
2. **Satisfaction is explainable per requirement.** The assembled context shows, for each requirement, what satisfied it and at what epistemic status. Explainability is the trust brand, preserved at the new layer.

Interfaces: the same three surfaces as v1, upgraded. The MCP tool becomes build_context(task), returning the assembled, requirement-organized context to a connected assistant. The web UI keeps a "describe your task" mode producing the same assembly as copyable context. A plain rendered assembly remains as the fallback for tools with no connection.

## 3. The graph exists for inference, not indexing

V1 graph thinking: store relationships so retrieval can walk them. V2: the graph **reasons**. Entities and typed edges (works_at, part_of, uses_skill, built_with, managed_by, learned_from) plus the stores above support derived conclusions that were never stored.

Worked example: "Can Saloni interview for Baseten?" Nobody stored that. The graph holds Firefly, part_of Adobe's video generation work; built_with CUDA kernels and Triton; skills in inference optimization and production ML, each with project evidence. The inference composes them: CUDA plus inference optimization plus production ML at scale matches Baseten's core work, at high confidence, **and shows the path** (the three edges and the evidence under each). An inference without a visible proof path is a hallucination with good branding; in Memline every inferred item carries its path and its epistemic status, and can be confirmed or rejected by the user, which promotes or kills it.

Inference rules are deliberately boring at first: path composition over typed edges, skill aggregation from project evidence, recency weighting. Learned inference comes later and inherits the same rule: no path, no claim.

## 4. Goals are a store, not a field

V1 modeled who the user is. Nothing modeled where they are going, and recommendations suffered for it: context that ignores goals is biography, and biography does not change decisions.

Goals are first-class objects: statement, horizon, status (active, paused, achieved, abandoned), linked projects, linked principles, and progress signals. Active goals reshape the system continuously:

- **Task models** pull goal requirements into unrelated-looking tasks (see the negotiation example).
- **Ranking** changes: facts and narratives that serve an active goal outrank equally relevant facts that serve none.
- **Fit checking** (the v1 "simulation" idea) becomes mostly goal checking: would this context, this draft, this recommendation move the active goals forward or sideways?
- **Staleness detection:** a goal with no linked activity for its horizon gets surfaced, not silently carried. Goals expire and are renegotiated with the user, like every other understanding in the system.

## 5. Principles onboarding: teach me how you make decisions

Principles are close to being the product on their own, so onboarding changes. Not "tell us about yourself" but **"teach me how you make decisions"**: twenty questions, answered once, revisited rarely, producing six profiles: **decision profile, communication profile, leadership profile, writing profile, product philosophy, risk profile**. Each answer becomes a principle with the user's own words as evidence, editable forever.

The twenty questions:

Decision profile
1. When you have to choose and the data is incomplete, what do you actually do?
2. Describe a decision you are proud of. What made it the right call?
3. Describe a decision you regret. What did you learn about how you decide?
4. When two options are close, what breaks the tie for you?

Communication profile
5. How do you want bad news delivered to you: direct, softened, or with options first?
6. What do you always edit out of drafts other people or AIs write for you?
7. When you explain something hard, what structure do you reach for?

Leadership profile
8. What do you believe about giving feedback that most people get wrong?
9. When a team disagrees with you, what do you do first?
10. What would people who have worked for you say your style is, honestly?

Writing profile
11. Show or describe a piece of writing that sounds like you at your best. What makes it yours?
12. What words, phrases, or tones should an AI never use in your voice?
13. Do you write to persuade, to inform, or to think, most of the time?

Product philosophy
14. What makes a product good, in one or two sentences you actually believe?
15. When a product you built failed, what was the real reason?
16. What do you refuse to build or ship, even if it would work?

Risk profile
17. Where in your life are you conservative, and where are you a gambler? Give one example of each.
18. What is the biggest risk you have taken that paid off? What did it cost you on the way?
19. How much runway or safety margin do you need before a bold move feels right?

Goals bridge (this is where Section 4 gets seeded)
20. In two years, what would have to be true for you to say the period went well? List the two or three outcomes that matter most.

"Here is what I learned" is the payoff moment: after the twenty, the system presents the six profiles back, stated as understanding with epistemic status, and the user corrects them. Correction is the product working as intended, not a failure of the interview.

## 6. Narratives: memory the way humans actually keep it, and reasoning primitives once they grow up

Humans do not store "worked at Adobe, worked at Wayfair". They store the story: why she left, what she learned, how her interests moved from one place to the next. Narratives compress thousands of facts into a form LLMs use far better than fact lists, because a narrative carries causality and emphasis, not just data.

A narrative is an authored, approved artifact in the system: a short structured story (arc, turning points, lessons, current chapter) over a domain of a life: career, a project, a relationship with a field, a health journey. Sources: the user narrates, or the engine drafts one from facts, projects, and decision records and the user edits it in the inbox flow, the same approval discipline as everything else (an unapproved narrative about a person is a liability, not a feature). Narratives are what task models retrieve for open-ended tasks (introductions, bios, interviews, applications), where the story is the context. Facts are what they retrieve for precise tasks. The system needs both, and now has a place for each.

**In v3, narratives are also executable.** Every narrative exposes structured primitives, not just prose:

- **Lessons.** What this chapter of life taught, stated as transferable claims.
- **Patterns.** Recurrences across the story ("joins for the technical problem, leaves when the work becomes maintenance").
- **Mistakes.** Named, with their costs, in the user's own framing.
- **Advice.** What the user, knowing this story, would tell someone entering the same situation, which is also what they would tell themselves.
- **Evidence.** The facts, projects, and decisions underneath each of the above, so any primitive can be audited.

With those fields, the engine answers questions that fact retrieval handles terribly: "What usually causes me to leave jobs?" is answered by aggregating Patterns across the career narrative (checked against Evidence), not by fetching forty loosely related facts and hoping the assistant notices the theme. Narratives become reasoning primitives: task models can require "the relevant pattern from the career narrative" the way they require a compensation figure, and the fit check can test a plan against the user's own recorded Mistakes. This is the strongest compression in the system: thousands of facts, one story, and the story can be run.

## 7. Uncertainty: epistemic states replace the confidence number

A scalar confidence score hides the thing the user actually needs to know, which is **how** something is known. Every item in every store carries one of four epistemic states:

- **Known.** Stated by the user, or confirmed by them. Usable as fact.
- **Likely.** Strong evidence (multiple observations, graph inference with a solid path), not yet confirmed. Usable, labeled.
- **Hypothesis.** A pattern the engine suspects (for example, "probably prefers concise writing", evidence 78 percent, from observed edits). Never presented as fact; a candidate for a one-tap confirmation that promotes or kills it.
- **Unknown.** A requirement the system knows it cannot satisfy. Stated as a gap, never papered over.

The numeric evidence stays underneath (sources, confirmations, last confirmed, contradictions), because the states need an audit trail; but the user and the receiving assistant see the state, not a naked percentage. Promotion and demotion are events with reasons: a Hypothesis becomes Known when the user confirms it; a Known fact becomes contested (a visible fifth condition on Known items) the moment a contradictory item is approved, until the user resolves it. This is more human than a score, and it is the mechanism that lets inference (Section 3) exist without poisoning trust: inferred things are born Likely or Hypothesis, and only the user makes them Known.

## 8. The fourth operation: challenge

V2 gave the engine three operations: extract, infer, revise. V3 adds the one that makes it a partner rather than a database: **challenge**.

A challenge is reflective reasoning over the whole model: the engine compares what the user says they value with what their approved decisions actually do, and when the gap is real and repeated, it asks. The canonical case: a user states "I want work-life balance" for months, while every approved decision record favors compensation over free time. Eventually the engine surfaces, in the inbox, as a first-class item with its evidence: "You consistently choose compensation over free time. Has your priority changed?" The user answers once: the principle is revised, the goal is revised, or the pattern is acknowledged as a deliberate exception. All three outcomes improve the model. None of them is an inference, and none is a correction of a fact. It is the system noticing the person.

Rules that keep challenge welcome instead of annoying: a challenge requires repeated evidence (never one decision), it always shows its evidence, it is rate-limited (a reflective question is a rare event, not a notification stream), it can be dismissed permanently per pattern, and it never edits the model on its own. Challenges target Principles, Goals, and Identity, in that order of frequency; an Identity-level challenge ("you have described yourself as an engineer for six years; your last year of decisions looks like a founder's") is the rarest and most valuable output the engine can produce.

## 9. Compounding understanding: reflections first, opportunities second

Everything above answers tasks. This section stops waiting to be asked, and v3.1 corrects its own framing: **this is not a notification system. It is compounding understanding.**

The primary output is the **reflection**: a periodic, evidence-backed account of how the user is changing, computed by diffing the model against its own history in the evidence ledger. After a year, the valuable outputs sound like this:

- "You have gradually become more interested in research than management." (Project and goal evidence, trended.)
- "Your writing has become more concise." (Writing Style evidence, measured across drafts.)
- "Your risk tolerance has increased." (Decision records, compared across periods.)
- "Your projects increasingly involve CUDA." (Project evidence, counted.)
- "Your goals are drifting toward founding a company." (Goal edits plus identity evidence, surfaced as a challenge if it crosses into contradiction.)

These are not notifications, and they are not tips. They are the product noticing a person changing, which is something no assistant that met you last week can do and something a user may genuinely miss if they stop using the product. Reflections are delivered rarely, as a composed piece (monthly at most), each claim carrying its evidence and its trend, each one confirmable, correctable, or dismissible, and every correction feeds the model.

**Opportunities** are the second output class, a special case of reflection pointed outward: the stores, read together, describe a frontier (active goals, missing requirements, computed skills, identity trajectory), and occasionally the match is strong enough to name. Canonical case: the model knows the user is interviewing, holds an active Staff goal, and computes deep CUDA and inference skills from project evidence, so it says "You look like a strong fit for Staff ML roles at Baseten, Anthropic, and Together AI", with proof paths attached and Unknowns named. This still changes the relationship from retrieval to partnership, but the partnership is earned by the reflections first: a system that has accurately told you how you are changing has the standing to tell you where you might go.

Guardrails, because proactive systems die by spam: reflections and opportunities are rare by design (a high bar of goal relevance times longitudinal evidence strength, not recency), every claim carries its reasoning and its Unknowns, dismissal is one tap and teaches the engine (dismissed categories decay), and none of it ever leaves the user's own surfaces. A reflection with no evidence trend is horoscope copy; with one, it is the deepest moat in this document, because a year of compounded, user-corrected reflections cannot be imported, scraped, or rebuilt by a competitor in a weekend.

## 10. What happens to the shipped v1

Nothing is thrown away. The mapping:

- The memories table becomes the Facts store, gaining epistemic state, persona facet, and valid_from and valid_to where they apply.
- The inbox stays the universal gate: facts, principles, hypotheses, narrative drafts, and inferred skills all arrive there with evidence. Approval-first is untouched; it is the trust primitive the whole engine stands on.
- The rendered assembly (internally still called a pack in code) stays, as the export format of a task model assembly for unconnected tools. See Section 11 on language.
- MCP grows build_context(task) beside recall and propose; propose now accepts typed proposals (fact, preference, principle, decision, hypothesis).
- The starter interview is joined, and eventually overshadowed, by the Principles interview (Section 5). Facts onboarding asks "who are you"; principles onboarding asks "how do you think". The second is the product.

## 11. Language: "Context Packs" is retired

"Context Pack" was v1 implementation language that leaked into the product. Under this architecture the user asks for help with a task and context arrives, assembled; nobody should have to learn the word "pack" to use the product. The term stays in the codebase where it is a useful internal name for a rendered assembly (tables, API, file formats are not user language), and it is being removed from product copy, documentation framing, and the UI. The user-facing words are **context, assembled for the task**: "assemble context for ChatGPT", "your context for this task includes, and is missing". Same rule retires "personal memory" as the headline: the product builds a living model of the user; context is what the model emits.

## 12. Build order under the new architecture

0. **Language and framing** (hours): the vision sentence and user-model category go on the landing page and into the docs (done in STRATEGY.md), and "packs" leaves the product copy (done in the UI in the same pass as this document).
1. **Epistemic states and facets on the existing store** (schema, UI, task weighting). Small, foundational, everything later reads these fields. Identity is seeded here as a store (items arrive from the starter material and narratives for confirmation).
2. **Task Models v1**: a library of task models for the top task families, requirement satisfaction over the existing stores, the build_context MCP tool, missing-requirement prompts. This replaces retrieve-rank-compress as the assembly path.
3. **Principles and Identity capture**: the six profiles, the twenty-question onboarding, the "here is what I learned" review, principles and identity as stores the task models and fit check read.
4. **Goals**: the store, goal-aware ranking and task models, staleness surfacing.
5. **Graph, computed skills, and inference**: entities and edges derived at approval time, skills computed as a view over projects and evidence, path-showing inference, confirm-or-kill for inferred items.
6. **Narratives as executable primitives**: structured lessons, patterns, mistakes, advice, and evidence; drafting from stores; approval flow; pattern-level questions answered across narratives.
7. **Decision capture, Decision Models, and challenge**: decision records deepen principles and the fit check, and power the challenge operation (Section 8) once there is enough decision history to reflect on.
8. **Compounding understanding** (Section 9): reflections first, opportunities second, last in the order deliberately, because a system earns the right to speak first only after it has been accurate while being asked.

But none of this order outranks the wedge. Added 2026-11-01, and it overrides the rest of this section where they conflict: **the next milestone is not a build step in this list. It is an empirical demo** (specified in PRODUCT.md): a real person imports their ChatGPT history, reviews the proposed understandings, approves most of them, opens Claude, and feels that Claude already knows their work, inside five minutes. The architecture exists to make that moment deeper over years; the demo decides whether there are years. If the moment does not land with imported history alone, steps 1 and 2 get built only in the form that makes it land.

Sequencing logic: states before reasoning (nothing inferred is safe before the system can label it), task models before graph (requirements tell the graph what to prove), principles before simulation (no values, no fit check), narratives after the stores they compress exist.

Displacement, unchanged from the earlier assessment: this competes with Stripe and launch for the same hours. Under the new framing the recommendation sharpens: steps 1 and 2 are the architecture becoming real and should precede Stripe, because they change what a first user experiences in the first ten minutes. Steps 3 onward can grow with the user base.
