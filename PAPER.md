# FATHOM: Helpful, Not Omniscient

Working notes toward a paper. Adaptive PDA guidance for preserving fear in Subnautica-like exploration.
Al (Ontario Tech University), supervised by Dr. Cristiano Politowski, Code & Sorcery Lab. Poster at CSER 2026 Fall.
Everything below distinguishes what is measured from what is planned. Numbers dated 2026-09-07.

## Abstract (draft)

Survival exploration games derive tension from not knowing what is out there. A conventional AI assistant
threatens that tension by over-explaining and over-guiding. FATHOM is a diegetic AI companion that lives in the
PDA of Subnautica 2, watches player state through a UE4SS telemetry mod, and emits brief in-world lines only after
meaningful triggers, in the game's original PDA voice. Its design principle is graded withholding: the companion
stays vague while vagueness costs nothing and becomes concrete only at the moment concreteness is survival. A
system-side escalation variable, dread, steers tone, degrades the voice, and permits at most one deliberately
false contact per dive. We report the architecture, a scripted-scenario evaluation of relevance, persona tracking,
fallback rate and latency, and a behavioural-proxy method that scores player reactions after each line against a
random-moment baseline. We argue that the interesting problem is not guidance but restraint.

## Research question

Can an adaptive AI companion provide useful guidance while preserving uncertainty, tension and immersion in
survival exploration?

Sub-questions the prototype makes testable:

1. Does a line change what the player does in the next 20 s, relative to random quiet moments? (behavioural)
2. Does graded withholding (vague far, concrete at contact) read as helpful rather than as a map? (self-report)
3. Does the escalation variable produce reported tension, and does its false-contact line register? (self-report)

## Background

- **Fear as the unknown.** Community discourse on making Subnautica frightening converges on the unknown, stakes,
  and sensory deprivation: not knowing what a sound is, permadeath, playing dark with headphones, playing without
  the HUD or without sound, "when you know where things are but not how close they are." Familiarity is named as
  the thing that kills it. (r/subnautica thread 16pdzth; Steam community discussions; see References.)
- **The PDA as minimal diegetic messaging.** The original game's PDA is a synthetic voice with a small set of
  clipped lines. Its most quoted line withholds everything but a category and a question. It is the design
  precedent for a companion that speaks less than it knows.
- **The original PDA voice is a synthesizer.** IVONA 2 "Amy", a British English TTS voice from around 2013, under
  a fixed chain of pitch shift, equalisation, flangers and chorus. The chain is public in the SnPdaVoice repository.
  Consequently reproducing the voice raises no performer-rights question, though the IVONA engine itself is
  proprietary and discontinued; Amazon Polly's standard "Amy" is its successor.

## System

Pipeline: game telemetry, situation vector, persona steering, PDA-style line, latency-bounded fallback, voice.

**Telemetry (UE4SS Lua, 2 Hz, game thread).** Depth, oxygen seconds (from the HUD's oxygen view model, which
mirrors the survival attribute set), speed, position, nearest threat distance and class (Collector and Void
leviathans; the placid Deepwing Brooder is excluded), the threat's relation to the diver in words (above/below,
ahead/behind), nearest structure (lifepod, base hatch, Tadpole), nearest air source (oxygen plant, tank,
generator, replenish box, Tadpole), and time of day from the day-sequence actor. The mod performs no object
scanning and reads no properties beyond those verified; see Engineering notes.

**Situation vector.** Six flags: threat contact (< 20 m or < 2 s to contact), oxygen critical (< 12% of capacity),
threat near (< 60 m or < 6 s), low oxygen (< 40%, ahead of the game's own 25% alert), deep zone (> 200 m),
lost (> 1.5 km from any structure). Four linear signals in 0 to 1 with the flag threshold at 0.5 (oxygen, threat,
lost, depth). Time to contact is range over closing speed, so a fast approach is near before it is close.

**Persona steering.** survivor = 2 × max(oxygen, threat), navigator = lost, explorer = 1 − max(survivor,
navigator), normalised; argmax speaks. The factor two encodes "life outranks the way home". Each persona has a
style instruction; a tone instruction is selected from dread.

**Trigger policy.** Silence is the default. A line fires when a flag rises (most urgent first), or when the persona
or the dominant signal changes after a 10 s cooldown. Unprompted lines: after 180 s of silence below 200 m with
dread ≥ 0.6, one ambient line; with dread ≥ 0.8, no creature in range and probability 0.35, at most once per
session, a phantom contact.

**Register.** The line set of the first game (222 lines with triggers) and the databank of the second (41 creature
entries, each closing in an assessment) were analysed to derive the PDA's register: six sentence shapes (prefix and
condition; "Detecting" and reading; "Scans indicate" and fact; fact and verdict; corporate survival advice; the
deadpan tag), present tense, impersonal, severity carried by Caution/Warning/Emergency rather than adjectives, a
horrifying fact delivered at the pitch of a routine one, no metaphor. The analysis is in `docs/pda_register.md`.
The prompt, every template and the quiet-minute pool were rebuilt on it.

**Language model.** gemma3:4b on Ollama, locally, 2.5 s budget, 30 tokens, temperature 0.3. The model receives the
situation in the register's own nouns ("Oxygen reserve low. A large lifeform is in the immediate vicinity."), never
numbers, with the register's shapes and seven of the game's lines as examples. Output is rejected, and the template
plays, if it does not open the way the PDA opens, contains a digit, a bearing word, a percentage, no word from its
topic's vocabulary, or a word from a short "purple" list (stirs, breathes, abyss, void, vast), which a 4B model
reaches for when asked to be unsettling. Critical topics (contact, oxygen critical, phantom) bypass the model and
play a cached template at 0 s. Unprompted ambient lines come from a pool of eleven original lines in the register
("Scans show the digestive tracts of nearby lifeforms contain tissue of unknown origin."), rotated without repeats.
Creature lines (six) and depth lines (five) are pooled as well, because the model, asked about a lifeform,
describes anatomy the PDA never would, and asked about depth beside a note on the light loses the thread; the
model is left the two situations where phrasing depends on context: oxygen, with its air sources and the
reachable-surface test, and the way back. This division is itself a finding: a 4B model can hold a register when
the situation has variables, and a fixed situation is better served by fixed lines, which is also how the game
does it. Templates are the only lines that may point anywhere, and only at contact or when
naming the surface or an air source.

**Oxygen honesty.** The system computes whether the remaining air reaches the surface at 2 m/s. When it does not,
"ascend" is replaced by "the surface is out of reach", with "replenish now" when an air source is within 40 m.

**Dread.** d' = 1/600 [z > 200] + 1/900 [dark] + zone rate (1/300 presence, 1/120 near, 1/40 contact)
− 1/120 [surface or by a structure], plus 0.15 per crisis line, clamped to [0, 1]. Tone bands at 0.33 and 0.66.
Above 0.5 the cached audio is degraded at playback (dropouts, stutters, bit-crushed patches; above 0.9, a 30%
chance the line is cut). Dread is explicitly a system variable, not a measure of the player.

**Voice.** Lines are fetched once from Lee23's generator (IVONA Amy plus the filter chain) and cached by text;
Windows speech is the offline fallback. Latency on a cache miss is about 5 s, which is why critical lines are
pre-cached templates.

## Evaluation design

### Scripted scenarios (implemented, measured)

Eleven scenarios, one frame per second: oxygen crisis shallow and deep, a leviathan approach, a compound crisis
(air falling while a leviathan closes), lost, deep entry, lost and deep, a seven-minute quiet dive at 300 m, an
ambush at 16 m/s, a trapped diver with a plant nearby, and a control with nothing wrong. Metrics: relevance (the
line about the crisis carries the expected persona), persona tracking (the last line is about the tracked
crisis), fallback rate among model-eligible lines, median latency, and phantom count.

| Metric | Poster target | Measured (gemma3:4b, offline sim) |
|---|---|---|
| Relevance | 7/8 | 11/11 |
| Persona tracking | 8/8 | 11/11 |
| Fallback rate | ≤ 14% | 0% of 10 model lines; 11 critical and pooled lines by design |
| Median latency | 1.2 s | 1.2 s with the GPU shared by another application, 0.25 to 0.7 s idle |
| Silence in the control | required | held |

These are mechanical checks of the policy, not measures of experience.

### Behavioural proxies (implemented, one diver so far)

For each line, the 20 s after it against the 10 s before: speed change, seconds stationary (≤ 0.3 m/s), ascent
(≥ 2 m shallower), closing on home, distancing the threat, heading reversal (> 120°). The same record is computed
at up to 30 random moments with no line within 30 s, as the baseline. Reported per topic and against baseline.
With one diver and a handful of lines this describes dives; it becomes evidence with participants.

### Self-report (planned)

Within-subject, two conditions per participant in counterbalanced order: FATHOM on, FATHOM off. Short dives with
a scripted crisis. Tension and immersion via the Game Experience Questionnaire core module (tension and
sensory/imaginative immersion components), plus a one-item probe after each line ("did that help / did that
tell you too much"). Sample of 12 to 20 is realistic for a course project.

### Physiological (not planned for the poster)

Heart rate or electrodermal activity would strengthen the tension claim; out of scope.

## Threats to validity

- **Single developer as the only diver.** All in-game numbers so far come from one person who knows the system.
- **The sim is scripted by the same author who tuned the thresholds.** Relevance 11/11 says the policy does what it
  was told, not that it is right.
- **Model variance.** Lines vary run to run; the guards bound content but not quality.
- **Dread is not fear.** It is a designed curve. Any claim about player dread must come from the study.
- **Voice dependency.** The genuine PDA voice comes from a fan-run service. Fine for a prototype at this volume,
  not a foundation for a study; the replacement is Polly Amy under a local port of the public filter chain.
- **Early Access target.** Subnautica 2 changes monthly; class names in the telemetry mod will drift.

## Engineering notes worth reporting

UE4SS Lua on this Unreal 5.6 build crashed the process on: property type introspection, reading arbitrary
properties by name, cached actor references across garbage collection, and any state surviving "Restart All Mods".
These are unrecoverable by `pcall`. The stable subset is: `FindFirstOf`, `FindAllOf`, `IsValid`,
`K2_GetActorLocation`, `GetVelocity`, a verified property on the HUD view model, and `pcall`-wrapped UFunction
calls. Exploration should use UE4SS's object dumper rather than Lua. Separately, Ollama on Windows: use 127.0.0.1
not localhost (2 s IPv6 penalty), and give the warm-up and the real call identical options or the model reloads.

## Future work

Creature temper from behaviour attribute sets so threat is mood, not distance. Yielding to the game's own PDA
playback. Local voice synthesis. Participants.

## References (verify before citing)

- IJsselsteijn, W. A., de Kort, Y. A. W., & Poels, K. (2013). *The Game Experience Questionnaire.* Eindhoven:
  Technische Universiteit Eindhoven.
- LeeTwentyThree. *SnPdaVoice*, https://github.com/LeeTwentyThree/SnPdaVoice, and https://subnauticapdavoice.com/
- UE4SS, https://github.com/UE4SS-RE/RE-UE4SS
- r/subnautica, "How do I make subnautica more scary for myself?" (2023), thread 16pdzth.
- Subnautica 2 wiki entries for the Collector Leviathan and Deepwing Brooder; PC Gamer and GameSpot oxygen guides
  (2026), for creature behaviour and oxygen sources as of Early Access.
