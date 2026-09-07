# Enclosure Brainstorm — "The Cat" 🐱

Turning the parts pile into a kid-friendly cat the kids talk to. Crude sketches,
wild ideas, nothing committed yet. Theme is set by the **Big Kitty Paw Key** —
lean all the way into "cat."

## The pieces we have to place (and what each one *needs*)

| Part | Shape / size | Placement need |
|---|---|---|
| **Jetson Orin Nano Super** | ~10×10×5 cm + **active fan** | Hidden, but **needs airflow** and **rear ports reachable** (USB×4, USB-C, DisplayPort, Ethernet, DC power) |
| **ReSpeaker XVF3800** | round disc, **LED ring** on top | Exposed, **facing up/out**, away from the speaker; LED ring should be **visible** (it's the "listening" glow) |
| **Pebble V3 speakers** | **two orbs** + cable | Drivers face outward; natural **pair** → ears or eyes |
| **Big Kitty Paw Key** | big paw button | **Front, low, kid-height, easy to slap**, on something that won't tip |
| **Powered USB hub** | small box + brick | Hidden; everything plugs into it |
| **Power bricks ×2** | Jetson + hub | Hidden; cables exit **back/bottom** |

### Hard engineering rules (apply to every concept below)
- 🔥 **Vent the Jetson.** The fan needs intake + exhaust. Never fully seal it. Put the fan over a grille (bottom or back).
- 🎤 **Separate mic from speaker.** Put the ReSpeaker up high/forward and the speaker(s) off to the sides — physical distance helps even with the XVF3800's echo cancellation.
- 💡 **Show the LED ring.** Diffuse it through translucent plastic / a mesh / a light-pipe so "I'm listening" reads across the room.
- 🧱 **Heavy, wide base.** Kids will *whack* the paw. Weight the bottom (steel plate, sand, tile) so it can't tip.
- 🔌 **Rear debug hatch.** A removable/magnetic back panel that lines up with the Jetson's ports, so you can jack in keyboard + mouse + DisplayPort when SSH fails.

## Cat anatomy ↔ component map (the fun part)

```
             /\        /\          EARS  = Pebble V3 orbs (sound from the ears!)
           /  \      /  \
          ( P  )    ( P  )
           \__/  __  \__/
            .----(##)----.          CROWN/HALO = ReSpeaker LED ring,
           /    (####)    \                       glows when listening
          |  (o)      (o)  |        EYES  = printed/LED, or fiber-optic
          |       /\       |        NOSE  = small speaker OR "boop to talk" button
          |   ~ ~( ω )~ ~  |        WHISKERS = wire / fiber optic; MOUTH grille = mic
          |                |
          |    [ PAW! ]    |        PAW   = Big Kitty Paw Key, front & center
          '----------------'
          [== heavy base ==]        BODY/base hides Jetson + hub
                 ||                  cables out the back -> "tail"
              (rear hatch)           ports reachable here
```

Two activation philosophies to pick from:
- **Paw-to-talk** (your default): slap the front paw → it listens.
- **Boop-the-nose** (wild): relocate the button as a springy nose — "boop" to talk. Maximum delight, but the paw is more robust for little hands.

## Build concepts

### 1) 🧱 LEGO cat (most kid-friendly, most iterable) — ~$60–150 bricks
A hollow brick body with a removable back wall. Rebuild/restyle anytime; kids help.

```
 front          back (hatch removed)
 [ /\  /\ ]      [::::::::::::]
 [ o  o   ]      [:  Jetson  :]  <- slide-out brick wall
 [  PAW   ]      [:  ports → :]  <- USB/DP/power exposed
 [========]      [: fan vent :]
```
- **Pros:** modular, no tools, hatches = just remove bricks, kids love it, vents are free (gaps).
- **Cons:** brick count adds up; need a rigid internal frame (Technic beams) so it doesn't sag; speaker/mic openings need planning.
- **Buy:** bulk LEGO / a LEGO "cat" or "creature" set as a starting kit; Technic beams + plates for the frame. Mount the Pebbles in brick "ear cups."

### 2) 📦 Cardboard / foamboard mockup (do this FIRST, ~$15)
Cheapest way to nail dimensions, port alignment, and mic/speaker placement before committing money. Kids decorate it with markers.
- **Pros:** instant, free-form, disposable, great for getting the *proportions* right.
- **Cons:** not durable, not the final form. Treat as the prototype.
- **Buy:** foamboard + hot glue + craft knife (hardware/craft store). Box cutter + a cereal box works in a pinch.

### 3) 🪵 Wooden cat box (sturdy, "real furniture" feel) — ~$25–60
A wooden cube/birdhouse-style body; cat face routed/painted on the front; ears mounted on top; drill holes for mic, speakers, ports. Felt-lined.
- **Pros:** heavy (won't tip), durable, looks intentional, easy rear access door (hinge + magnet).
- **Cons:** tools (drill, saw), less "toy," harder to restyle.
- **Buy:** unfinished wood box / birdhouse / cigar box, hinges, magnetic catch, hole saw, speaker grille cloth (hardware/craft store).

### 4) 🖨️ 3D-printed cat shell (most polished) — filament cheap, or ~$50–150 printed-for-you
Custom shell with proper speaker grilles, an LED-ring light pipe, snap-fit rear hatch, and exact port cutouts. Print in a couple of panels.
- **Pros:** purpose-built, clean grilles + light diffusion, repeatable, screw bosses for everything.
- **Cons:** needs CAD + a printer (or a print service); slowest to first version.
- **Buy:** filament if you have a printer; otherwise a service (Craftcloud/JLCPCB/local library makerspace). Start from a remixable "cat" model on Printables/Thingiverse.

### 5) 🧸 Plush-cat skin over a hard frame (softest, most huggable) — ~$25–50
Gut a **large plush cat**; build a rigid internal "skeleton" (3D-printed/LEGO/foamboard) that holds the Jetson, mic, and speakers; the plush is the outer skin. Mic peeks through a mesh patch; speakers behind thinner fabric; paw button sewn into a front paw.
- **Pros:** irresistibly kid-friendly, safe to whack, hides everything.
- **Cons:** heat (fabric traps it — must duct the fan to a vent hole), fabric muffles mic/speaker (use thin mesh windows), rear access = a zippered/velcro back flap.
- **Buy:** big plush cat (Amazon/IKEA), velcro/zipper, speaker mesh, internal frame parts.

### 6) 🏺 Repurposed object (fast & characterful)
A ceramic **cat cookie jar**, cat planter, or cat-shaped tin — already cat-shaped; cut openings. Cookie jars are great: the **lid is your top access hatch** and the wide ceramic base adds weight/stability.
- **Pros:** instant cat silhouette, heavy base, lid = built-in hatch.
- **Cons:** drilling ceramic is finicky; fixed shape; airflow needs cut vents.

### 7) 🏰 "Cat castle" / cat-tower tie-in (stretch)
Build it into a small cat-themed shelf or play structure the kids already vibe with. The jukebox is the "head" on top; the body is a cubby.

## Wild / stretch features (sprinkle onto any build)
- ✨ **Halo that breathes** — the ReSpeaker LED ring already pulses when listening; diffuse it through a translucent crown so it glows like a magic cat.
- 🌟 **Fiber-optic whiskers** that light up while listening (split the LED ring's glow into whisker strands).
- 👂 **Servo-wiggle ears** that twitch when it hears you (a future 40-pin GPIO project).
- 👃 **Boop-the-nose** secondary button (or make the nose the *only* button).
- 🏷️ **Collar + name tag** — let the kids name the cat; engrave/print the tag.
- 🐾 **Light-up paw** — translucent paw button with an LED so it beckons "press me."
- 🎨 **Theme it to the kids' world** — the Sonos queue had *Warriors* audiobooks and Ninjago; could skin it as a favorite character.
- 🔌 **Tail = cable run** — a fabric/wire tail that hides and routes the power cables out the back.
- 😴 **Sleeping vs awake** — eyes/LED dim when idle, brighten when listening.

## Recommended path (cheap → committed)
1. **Cardboard mockup first** (concept #2) — get proportions, port alignment, mic/speaker spots, paw height, and airflow right for ~$15. Let the kids decorate it; it doubles as a fun first version.
2. Once the layout works, commit to the "forever" build: **LEGO (#1)** if you want infinite iteration with the kids, **wood (#3)** for a sturdy furniture piece, or **3D print (#4)** for the most polished result.
3. Layer in stretch features (halo glow, whiskers, light-up paw) after it's functionally solid.

## Starter shopping list (mix & match)
- Foamboard + hot-glue gun + craft knife (mockup)
- Heavy base material: a tile, steel plate, or bag of sand/pennies
- Speaker **grille cloth / metal mesh** (mic + speaker windows)
- Translucent acrylic or vellum (LED-ring diffuser / glowing crown)
- Magnets or a small hinge + magnetic catch (rear debug hatch)
- Cable sleeve / split loom (tidy the two power cables → "tail")
- Adhesive standoffs / Velcro / zip ties (mount the Jetson + hub inside)
- Then your "forever" material: bulk LEGO **or** a wood box/birdhouse **or** filament/print service **or** a big plush cat

---
*Next:* pick a concept (or a hybrid), and I'll turn it into a concrete cut/parts
list with dimensions based on the actual component sizes.
