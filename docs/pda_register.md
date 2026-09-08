# The PDA register

How the Subnautica PDA actually talks, from the line set of the first game and the databank of the second, and
what FATHOM's prompt, templates and quiet-minute pool are built on. Researched 2026-09-07 from the Subnautica
wiki's dialogue page (222 lines with triggers), the 41 fauna pages of the Subnautica 2 wiki, and the creature
tier index. Short quotations only; the full lists are at the sources at the end.

## What the voice does

The PDA is an Alterra survival instrument that has been rebooted "in emergency mode with one directive: to keep
you alive on an alien world." Everything it says follows from that. It reports readings, issues verdicts, and
files paperwork, and it does all three in the same flat institutional voice whether the reading is a low battery
or the digestive tracts of nearby lifeforms. The humor is never stated. It comes from the gap between the fact
and the tone.

Six sentence shapes cover almost every line:

| Shape | Examples from the game |
|---|---|
| **Prefix + condition** | "Warning: oxygen, ten percent." "Caution: passing safe depth." "Emergency: hull breach detected." |
| **Detecting + reading** | "Detecting multiple leviathan class lifeforms in the region." "Detecting increased local radiation levels." |
| **Scans + fact** | "Scans indicate this structure is composed of a metal alloy with unprecedented integrity." |
| **Fact + verdict** | "Cause: unknown." "Reason unknown." "Explanation unclear at this time." "Adding report to databank." "Continuing to monitor." |
| **Corporate survival advice** | "Consider taking a seat and meditating." "Utilizing alien resources is a proven survival strategy." "Exploration is conducted at your own risk." |
| **The deadpan tag** | "Are you certain whatever you're doing is worth it?" "This is considered an optimal outcome." "They may also be studying you." |

Rules the line set obeys, which the prompt now enforces:

- Present tense, impersonal, institutional. No "I". "You" appears only in instructions and tags.
- Severity is carried by the prefix, not by adjectives: Caution, Warning, Emergency. No exclamation marks outside
  vehicle emergencies.
- A horrifying fact is delivered at the same pitch as a routine one, and is often followed by a bland
  administrative clause. That clause is the joke.
- Numbers appear only as oxygen and hull percentages. FATHOM withholds numbers by design and leaves the
  percentages to the game's own PDA.
- No metaphor, ever. Nothing "stirs", "breathes" or "consumes". The most emotional word in the entire line set is
  "Warning".

## The databank register in Subnautica 2

Every creature entry ends in an assessment: a one-line clinical verdict plus a recommended action.
"Apex predator. Avoid or distract." "Dangerous, territorial predator. Avoid or distract even when operating
submersibles." "Potentially hazardous in groups. Distract with flares and avoid close contact pending further
study." "Minor danger. Be alert for unpredictable attacks." "Mostly harmless. May provide emotional benefits."
The same two-beat shape, reading then verdict, is the model for every FATHOM line about a creature.

## What FATHOM says now

Templates, which play instantly and are the only lines allowed to point anywhere:

| Situation | Line |
|---|---|
| On start | Emergency companion online. Primary directive: keep you alive on an alien world. |
| Oxygen at 40% | Caution: oxygen reserve low. Consider beginning your ascent. |
| Oxygen at 40%, air source near | Caution: oxygen reserve low. A replenishment source is within reach. |
| Oxygen at 40%, surface out of reach | Caution: oxygen reserve low. Surface distance exceeds remaining supply. |
| Oxygen critical | Warning: oxygen critical. Ascend. |
| Oxygen critical, air near | Warning: oxygen critical. Replenish now. |
| Oxygen critical, surface out of reach | Warning: oxygen critical. Surface distance exceeds remaining supply. |
| Oxygen critical, both | Warning: oxygen critical. Surface distance exceeds remaining supply. Replenish now. |
| Contact | Warning: proximity contact. Below, behind you. Remain still. |

Depth lines are pooled, because a small model given "safe depth exceeded" and a note about the light produces
"the depth is unknown". Five lines, rotated without repeats:

- Caution: passing safe depth. Adding report to databank.
- Caution: passing safe depth. Continuing descent is not advised.
- Depth exceeds suit rating. Assessment: immediate ascent required.
- Warning: approaching crush depth.
- Caution: this suit is not rated for further descent. Exploration is conducted at your own risk.

Creature lines are pooled too, because a small model asked about a lifeform describes its anatomy, and the
PDA never does. Six lines, rotated without repeats:

- Detecting a large lifeform in the vicinity. Assessment: avoid.
- Detecting a leviathan class lifeform in the immediate vicinity. Are you certain whatever you're doing is worth it?
- Warning: large lifeform closing on this position. Consider remaining still.
- Lifeform behavior in this region is consistent with predation. Adding report to databank.
- Detecting a large lifeform with an interest in this position. Reason unknown.
- Caution: proximity to a large lifeform. Exploration is conducted at your own risk.
| Lost | No known structures within range. Retracing your descent is a proven survival strategy. |
| Deep | Caution: passing safe depth. Adding report to databank. |
| Phantom | Detecting a large lifeform in the vicinity. Bearing unresolved. |

The quiet-minute pool, rotated without repeats, written in the register rather than lifted from it:

- Local acoustic activity exceeds baseline. Continuing to monitor.
- Detecting a large lifeform in the region. Reason for its interest: unknown.
- Lifeform readings in this region are sparse. Explanation unclear at this time.
- Scans show the digestive tracts of nearby lifeforms contain tissue of unknown origin.
- Detecting unusually coordinated movement among nearby lifeforms. Reason unknown.
- Warning: entering a region with no prior survey data. Exploration is conducted at your own risk.
- Multiple lifeform signatures converging on this position. Are you certain whatever you're doing is worth it?
- Vital signs elevated. This is considered a normal response.
- Environmental scan complete. Results withheld pending your survival.
- Logging position. In the event of your disappearance, this data may assist recovery.
- Adding report to databank. Category: unexplained.

Model lines must start with one of the register's openers (Warning, Caution, Detecting, Scans, Lifeform,
Oxygen, Vital, No known, Assessment, and so on), must contain a word from their topic, and must not contain a
digit, a bearing, or a word from the purple list. Anything else falls back to the template above.

## Subnautica 2 creatures, Early Access, and how FATHOM treats them

From the creature index (43 archetypes in the May 2026 build, tagged by diet, size and archetype) and the wiki's
attitude fields. Actor class names are known only where the mod has seen them; the rest await an object dump.

| Tier | Creatures | FATHOM |
|---|---|---|
| **Leviathan, hunts you** | Collector Leviathan (`BP_CollectorLeviathan_C`), Shiver Leviathan and juvenile, Void Leviathan (`BP_VoidLeviathanChild_C` seen) | threat class, zones and contact |
| **Leviathan, ambush or hazard** | Great Jaw (sessile, snaps shut; a lithium source), Coral Crab | threat when moving toward it; to be classed once named |
| **Leviathan, placid** | Deepwing Brooder (`BP_DeepWingLeviathan_C`), the Reefback of this game | explicitly not a threat |
| **Predator** | Marrowbreach (apex, "avoid or distract"), Needler Mango (territorial), Nibbler Mango (packs, "distract with flares"), Sandspear, Twin Sitaray (attacks divers and electrical vehicles), Epicurean ("unpredictable danger to divers"), Foureye ("minor danger, unpredictable attacks"), Bullethead, Cerathecan, Hycean, Scourge Hive, Veps Defender, Waxmoon | predator tier, one warning line, half the leviathan dread rate, once class names are known |
| **Nuisance or defensive** | Hammerhead (aggressive attitude, herbivore), Quadrate (attaches, "may cause fatal dehydration"), Tongue Thief (parasite), Houndgar (its displays "may signal an imminent marrowbreach attack") | Houndgar is a tell worth its own line |
| **Passive** | Electric Geordie, Flash Slug, Geordie, Giant Tube Salp, Halfmoon, Hoverthorn, Periscopic Clowncrab, Pneuma, Snorkleback, Surge Jelly, Veps Sensor, Water Slug, Bloom Parasite, Jelly Ring, Jetocaris ("mostly harmless, may provide emotional benefits") | silence |

## Sources

- Subnautica wiki, Dialogue (Subnautica): https://subnautica.fandom.com/wiki/Dialogue_(Subnautica)
- Subnautica wiki, PDA: https://subnautica.fandom.com/wiki/PDA
- Subnautica 2 wiki, Fauna category and creature pages: https://subnautica2.fandom.com/wiki/Category:Fauna
- Subnautica 2 creature index with role tags: https://wikily.gg/subnautica-2/creatures/
- Collector Leviathan: https://subnautica2.fandom.com/wiki/Collector_Leviathan
- Shiver Leviathan: https://wiki.subnautica.com/sn2/Shiver_Leviathan
- Great Jaw: https://subnautica2.wiki.fextralife.com/Great_Jaw

Subnautica and the PDA lines quoted above are the property of Unknown Worlds Entertainment. They are quoted here
briefly for the purpose of describing a style. FATHOM's own lines are original.
