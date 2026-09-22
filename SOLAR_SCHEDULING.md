# Solar-Relative Scheduling Design Specification

## Status

Future feature specification.

Do **not** implement this feature merely because this file exists.

This document describes the intended behavior and architecture for a future scheduling system that supports:

* fixed wall-clock events
* sunrise/sunset-relative events
* daylight-fraction events
* seasonal schedule adaptation
* daylight-saving-time-safe behavior
* multiple switchable schedule profiles
* schedule preview and diagnostics

Before implementation, inspect the current scheduling architecture, pump-control logic, chlorination controller, SafetyGate, weather/astronomy infrastructure, configuration model, web UI, and tests.

Adapt this design to the current codebase rather than preserving obsolete APIs or assumptions from the date this document was written.

---

# 1. Purpose

The current pool schedule is primarily based on fixed wall-clock times.

That works for events such as:

```text
Run cleaner from 01:00 to 02:00.
```

However, many pool operations are more naturally related to sunlight.

Examples:

* chlorine dosing should generally occur near periods of solar chlorine demand
* daytime circulation requirements increase during long summer days
* shorter winter daylight can justify shorter daytime circulation
* hydraulic/filter tests may be useful near sunrise
* seasonal time shifts should not require repeatedly editing fixed clock schedules
* daylight-saving-time changes should not move a solar-relative event relative to actual sunlight

The future scheduling system should therefore support multiple time-coordinate systems.

The scheduler should resolve those abstract schedule definitions into ordinary timezone-aware concrete start/end times for each local day.

Downstream control code should operate on resolved concrete schedule windows and should not need to understand astronomy.

---

# 2. Fundamental Design Principle

Separate:

```text
WHEN something is allowed to occur
```

from:

```text
HOW MUCH treatment/circulation is required
```

Solar-relative scheduling determines **when** circulation, dosing, cleaning, or testing opportunities occur.

It does not determine chlorine demand itself.

For example:

```text
FC estimator:
    determines today's required chlorine quantity

Solar scheduler:
    determines today's eligible dosing windows

ChlorinationController:
    distributes the required dose through those windows

SafetyGate:
    determines whether each actual command is safe
```

Similarly:

```text
Solar scheduling:
    can lengthen summer pump windows

Weather/FC model:
    independently predicts actual chlorine demand
```

Do not use daylight duration itself as a substitute for the future weather/UV chlorine-demand model.

---

# 3. Scheduler Architecture

Conceptually:

```text
Schedule definitions
        |
        v
Astronomy / local date information
        |
        v
Daily Schedule Resolver
        |
        v
Concrete timezone-aware schedule windows
        |
        v
Existing pump/chlorination scheduling logic
        |
        v
CommandRouter / SafetyGate
```

The daily resolver should be the only layer responsible for converting:

* percentages of daylight
* sunrise offsets
* sunset offsets
* wall-clock times

into actual timestamps.

Downstream services should preferably receive ordinary resolved windows.

Do not scatter sunrise calculations throughout:

* ChlorinationController
* pump control
* SafetyGate
* web UI
* filter estimator

---

# 4. Supported Timing Modes

Support at least three scheduling modes.

---

# 4.1 Fixed Wall-Clock Time

Used for events whose relationship to sunlight is not important.

Example:

```yaml
timing: fixed
start: "01:00"
end: "02:00"
```

or:

```yaml
timing: fixed
start: "01:00"
duration_minutes: 60
```

Example use cases:

* overnight cleaner
* equipment maintenance cycle
* fixed service task
* winter overnight circulation
* manually selected fixed dosing window

Fixed events follow the local wall clock.

If the user specifies:

```text
01:00
```

the event should remain at 01:00 local civil time across seasonal sunrise changes.

---

# 4.2 Solar Anchor + Fixed Offset / Duration

Used when an event should move with sunrise or sunset but retain a fixed duration.

Example:

```yaml
timing: solar_anchor
anchor: sunrise
offset_minutes: -10
duration_minutes: 10
```

Meaning:

```text
Start 10 minutes before sunrise.
Run for 10 minutes.
```

Another example:

```yaml
timing: solar_anchor
anchor: sunset
offset_minutes: -60
duration_minutes: 90
```

Meaning:

```text
Start 60 minutes before sunset.
Run for 90 minutes.
```

Potential anchors:

```text
sunrise
sunset
daylight_midpoint
```

Support additional astronomical anchors only if a real use case emerges.

Do not over-generalize the first implementation.

---

# 4.3 Daylight Fraction

Used when both event placement and event duration should scale with daylight length.

Define:

```text
0%   = sunrise
50%  = midpoint between sunrise and sunset
100% = sunset
```

For a daylight fraction `p`:

```text
resolved_time =
    sunrise + p * (sunset - sunrise)
```

Example:

```yaml
timing: daylight_fraction
start_fraction: 0.30
end_fraction: 0.60
```

Meaning:

```text
Start 30% of the way through daylight.
Stop 60% of the way through daylight.
```

If daylight lasts 10 hours:

```text
window duration = 3 hours
```

If daylight lasts 15 hours:

```text
window duration = 4.5 hours
```

This gives automatic seasonal scaling.

---

# 5. Negative and Greater-Than-100% Fractions

Daylight fractions should intentionally support values outside:

```text
0.0 ... 1.0
```

Examples:

```text
-0.10 = 10% of daylight duration before sunrise
1.10  = 10% of daylight duration after sunset
```

For sunrise at 07:00 and sunset at 19:00:

```text
daylight length = 12 hours

-10% = 05:48
0%   = 07:00
10%  = 08:12
50%  = 13:00
100% = 19:00
110% = 20:12
```

This allows intuitive schedule expressions such as:

```text
-10% -> +10%
30%  -> 60%
```

The configuration may store normalized decimals:

```text
-0.10
0.10
0.30
0.60
```

while the UI displays percentages.

---

# 6. Daylight Midpoint Terminology

Do not call the 50% point "solar noon" unless using an actual solar-noon calculation.

For this scheduler:

```text
daylight_midpoint =
    halfway between sunrise and sunset
```

Use terminology such as:

```text
Daylight midpoint
```

This is clear and deterministic.

---

# 7. Local Timezone

All schedule resolution must use timezone-aware datetimes.

For the current installation, the local timezone is expected to be configured as something like:

```text
America/Chicago
```

Do not use naïve datetimes.

Do not assume UTC offsets are fixed throughout the year.

Timezone handling must correctly account for:

* DST start
* DST end
* historical/future timezone rules
* cross-midnight windows

---

# 8. DST Behavior

DST handling must be explicitly defined and tested.

---

# 8.1 Solar-Relative Events

Solar-relative events should naturally follow sunrise/sunset in local time.

When DST changes:

```text
sunrise local clock time shifts
```

and the resolved solar-relative schedule shifts with it.

No special DST correction should be required beyond correct timezone-aware astronomical calculations.

---

# 8.2 Fixed Events During Spring Forward

A configured wall-clock event may fall within a nonexistent local time.

Example:

```text
02:30
```

on the spring-forward date.

Define explicit behavior.

Preferred default:

```text
move to the first valid local time after the DST transition
```

rather than silently dropping the event.

This policy should be documented and unit tested.

---

# 8.3 Fixed Events During Fall Back

A local time such as:

```text
01:30
```

may occur twice.

A scheduled fixed event should normally execute once.

The scheduler must not accidentally duplicate an equipment event because the local clock repeats an hour.

Define and test which occurrence is selected.

A reasonable default is:

```text
first occurrence
```

unless a different policy is clearly preferable.

---

# 9. Cross-Midnight Windows

Support schedule windows such as:

```text
22:00 -> 08:00
```

as one continuous interval.

This is particularly important for winter scheduling.

Internally resolve as:

```text
Monday 22:00
through
Tuesday 08:00
```

Do not artificially split the interval into unrelated schedule events at midnight unless the existing architecture requires daily segmentation internally.

Even if segmented for implementation reasons, preserve the semantic identity of one continuous pump run.

This matters for:

* `no_dose_first_minutes`
* `no_dose_last_minutes`
* pump stabilization
* freeze behavior
* runtime accounting
* schedule preview

---

# 10. Multiple Schedule Profiles

Support multiple named schedule profiles.

Examples:

```text
normal
winter
party
service
vacation
```

Only one profile is normally active at a time.

Example conceptual configuration:

```yaml
schedule:
  active_profile: normal

  profiles:
    normal:
      windows:
        ...

    winter:
      windows:
        ...

    service:
      windows:
        ...
```

The active profile determines the normal planned schedule.

---

# 11. Schedule Profiles Are Not Safety Modes

Schedule profiles must remain operational scheduling choices.

They are not replacements for SafetyGate or freeze protection.

Priority should conceptually be:

```text
Safety overrides
    |
    v
Temporary/manual overrides
    |
    v
Active schedule profile
    |
    v
Resolved schedule windows
```

Example:

```text
active profile = normal
```

If freezing conditions require circulation:

```text
freeze protection overrides the normal profile
```

The user should not need to remember to select WINTER mode in order to remain protected from freezing.

The winter profile merely provides a more seasonally appropriate normal schedule.

---

# 12. Profile Switching

First implementation should support manual switching.

Example UI:

```text
Schedule Profile

(*) Normal
( ) Winter
( ) Service
```

The current profile should be visible prominently in the dashboard and schedule page.

Example:

```text
Active schedule: WINTER
```

Profile changes should:

* take effect predictably
* resolve the remaining schedule for the current day
* not create duplicate events
* not interrupt safety overrides
* be logged

---

# 13. Future Automatic Profile Selection

Automatic profile selection may be added later but is not required initially.

Possible future mechanisms:

```text
date range
forecast temperature
season
operator-defined rule
```

Examples:

```text
Use winter profile from Nov 15 to Mar 1
```

or:

```text
Use winter profile if overnight forecast minimum < 35°F
```

However, freeze protection remains independently authoritative.

Do not make freeze safety depend on profile-selection automation.

---

# 14. Daily Schedule Resolution

Resolve the active schedule into concrete windows for each local day.

Conceptually:

```text
Local date:
2026-06-21

Sunrise:
06:19

Sunset:
20:39

Daylight:
14 h 20 min
```

Then:

```text
normal profile
    |
    v
resolve each abstract event
    |
    v
concrete windows
```

Example:

```text
01:00-02:00   cleaner
06:09-06:19   hydraulic test
04:53-07:45   morning circulation
10:37-14:55   daytime circulation
```

Downstream control logic should work from these resolved windows.

---

# 15. Resolution Frequency

At minimum, resolve the schedule:

* at application startup
* at local midnight / start of each new scheduling day
* when the active profile changes
* when schedule configuration changes
* when timezone/location configuration changes

It is acceptable to resolve several days in advance for display purposes.

Runtime control should not depend on repeated astronomical calculations every control tick.

---

# 16. Astronomy Source

Use a deterministic astronomy implementation or trustworthy source to obtain:

```text
sunrise
sunset
```

for:

```text
date
latitude
longitude
timezone
```

Prefer calculations that do not require internet access at runtime.

Weather service availability should not be required merely to calculate sunrise and sunset.

If an existing weather provider supplies sunrise/sunset, it may be used as an auxiliary source, but the scheduler should ideally remain functional offline.

The implementation should clearly document the chosen astronomical calculation/library.

---

# 17. Location Configuration

Solar scheduling requires site location.

Use:

```text
latitude
longitude
timezone
```

as site-specific configuration.

Because the repository may be public, actual site coordinates should normally live in:

```text
pi-local.yaml
```

or equivalent site-local configuration.

Tracked example configuration should use:

```text
null
```

or clearly labeled example values rather than the real residence location.

If solar scheduling is enabled without valid location:

* fail configuration validation clearly
* do not silently use incorrect example coordinates
* fixed schedules may continue operating if architecturally practical

---

# 18. Missing Astronomy Data

The scheduler must define fail-safe behavior if sunrise/sunset cannot be calculated.

For a properly configured terrestrial site this should be rare.

Preferred behavior:

* fixed wall-clock events continue
* unresolved solar events are marked unavailable
* clearly notify/log the configuration/runtime problem
* do not invent times
* do not reuse stale sunrise/sunset indefinitely without indicating that it is stale

For the current installation latitude, polar-day/polar-night edge cases are irrelevant, but the implementation should still fail cleanly if astronomy returns no sunrise/sunset.

---

# 19. Event Model

Each schedule event should have a common set of operational properties independent of timing mode.

Conceptually:

```yaml
- name: daytime_circulation

  timing:
    type: daylight_fraction
    start_fraction: 0.30
    end_fraction: 0.60

  pump:
    enabled: true
    speed: low

  booster:
    enabled: false

  allow_dosing: true
```

Exact schema should follow project conventions.

Potential common fields:

```text
name
enabled
timing
pump state
pump speed
booster state
allow_dosing
priority if required
notes/description
```

Do not create separate unrelated schedule object types for fixed and solar timing if one event abstraction with different timing specifications is cleaner.

---

# 20. Duration Versus End Time

Where practical, allow schedule definitions to use either:

```text
start + end
```

or:

```text
start + duration
```

depending on timing type.

Examples:

Fixed:

```yaml
start: "01:00"
duration_minutes: 60
```

Solar anchor:

```yaml
anchor: sunrise
offset_minutes: -10
duration_minutes: 10
```

Daylight fraction:

```yaml
start_fraction: 0.30
end_fraction: 0.60
```

Avoid ambiguous combinations such as specifying both:

```text
end
AND
duration
```

unless validation clearly rejects conflicts.

---

# 21. Overlapping Events

The resolver must define deterministic behavior for overlapping events.

Examples:

```text
hydraulic test HIGH
overlaps
normal LOW circulation
```

Potential resolution policy:

```text
pump ON dominates OFF
HIGH dominates LOW
booster ON according to explicit priority/rules
allow_dosing only true where operational and safety rules permit
```

However, do not invent complex priority semantics unnecessarily.

Prefer schedule definitions that avoid ambiguous conflicts.

At resolution time:

* detect conflicts
* merge compatible windows
* reject or warn about incompatible overlapping commands
* expose conflicts clearly in UI/config validation

SafetyGate remains authoritative even if the schedule contains a conflict.

---

# 22. Continuous Pump Runs

After resolving all profile events, identify continuous pump-ON intervals.

Example:

```text
06:00-06:10 HIGH
06:10-08:00 LOW
08:00-09:00 LOW allow_dosing=false
```

should be recognized as:

```text
continuous pump run:
06:00-09:00
```

even though:

* speed changes
* dosing eligibility changes

This is important for:

```text
pump stabilization
no_dose_first_minutes
no_dose_last_minutes
runtime accounting
```

Pump speed changes should not by themselves reset the main-pump continuous-run timer.

---

# 23. Chlorination Interaction

Solar scheduling determines eligible circulation/dosing periods.

It does not calculate daily chlorine quantity.

Architecture:

```text
FC-demand estimator
    -> today's chlorine requirement

Daily resolved schedule
    -> dosing-eligible minutes

ChlorinationController
    -> distributes required dose

SafetyGate
    -> validates each actual pulse
```

The dosing algorithm should automatically adapt when daylight-relative windows change duration seasonally.

Example:

```text
summer eligible dosing time:
6 hours

winter eligible dosing time:
3 hours
```

If the required daily dose remains constant:

```text
chlorination duty/rate planning changes accordingly
```

Subject to maximum duty/rate safety limits.

---

# 24. no_dose_first_minutes

`no_dose_first_minutes` should be interpreted relative to the actual continuous main-pump ON interval.

Example:

```text
06:00-06:10 HIGH, dosing disabled
06:10-08:00 LOW, dosing enabled
```

If:

```text
no_dose_first_minutes = 1
```

then chlorine may begin at 06:10 because the pump has already been circulating for ten minutes.

Do not restart this delay merely because pump speed changes.

---

# 25. no_dose_last_minutes

Preferred semantics:

```text
no_dose_last_minutes
```

is relative to the end of the **continuous circulation run**, not merely the end of an individual dosing-enabled sub-window.

Example:

```text
13:00-14:00 allow_dosing=true
14:00-15:00 pump ON, allow_dosing=false
```

There is already one hour of post-dose circulation.

If:

```text
no_dose_last_minutes = 10
```

there is generally no reason to prohibit dosing during:

```text
13:50-14:00
```

just because the dosing-enabled sub-window ends at 14:00.

The final exclusion should apply near:

```text
14:50-15:00
```

but that interval is already not dosing-enabled.

This should be verified against the architecture that exists when solar scheduling is implemented.

---

# 26. Filter / Hydraulic Test Scheduling

Solar scheduling is well suited to the standardized filter-loading test.

Example:

```yaml
- name: hydraulic_test
  timing:
    type: solar_anchor
    anchor: sunrise
    offset_minutes: -10
    duration_minutes: 10

  pump:
    speed: high

  booster:
    enabled: false

  allow_dosing: false
```

The filter-loading estimator should remain passive:

```text
recognize qualifying HIGH / booster-OFF operation
```

It should not own or create the schedule.

Scheduler owns:

```text
when HIGH runs
```

Filter estimator owns:

```text
whether that run qualifies as a standardized hydraulic test
```

---

# 27. Seasonal Pump Runtime

Daylight-fraction windows naturally scale pump runtime with season.

Example:

```text
30%-60% daylight window
```

represents:

```text
30% of total daylight duration
```

So:

```text
summer:
15-hour day -> 4.5-hour interval

winter:
10-hour day -> 3-hour interval
```

This provides a useful first-order seasonal circulation adjustment.

Do not assume it perfectly models actual filtration requirements, bather load, temperature, or FC demand.

It is an operational schedule adaptation, not a chemistry model.

---

# 28. Winter Profile

A winter profile may intentionally move normal pump operation overnight.

Example:

```yaml
profile: winter

windows:

  - name: overnight_circulation
    timing:
      type: fixed
      start: "22:00"
      end: "08:00"

    pump:
      speed: low

    booster:
      enabled: false

    allow_dosing: true
```

Additional optional daytime event:

```text
small daylight circulation or hydraulic check
```

Freeze protection remains independent.

If weather becomes colder than expected:

```text
SafetyGate/freeze override keeps pump running
```

regardless of the selected profile.

---

# 29. Normal Profile Example

Conceptual example only:

```yaml
schedule:
  active_profile: normal

  profiles:

    normal:
      windows:

        - name: cleaner
          timing:
            type: fixed
            start: "01:00"
            duration_minutes: 60

          pump:
            speed: low

          booster:
            enabled: true

          allow_dosing: false

        - name: hydraulic_test
          timing:
            type: solar_anchor
            anchor: sunrise
            offset_minutes: -10
            duration_minutes: 10

          pump:
            speed: high

          booster:
            enabled: false

          allow_dosing: false

        - name: morning_circulation
          timing:
            type: daylight_fraction
            start_fraction: -0.10
            end_fraction: 0.10

          pump:
            speed: low

          booster:
            enabled: false

          allow_dosing: true

        - name: daytime_circulation
          timing:
            type: daylight_fraction
            start_fraction: 0.30
            end_fraction: 0.60

          pump:
            speed: low

          booster:
            enabled: false

          allow_dosing: true
```

These exact times/fractions are examples, not required defaults.

---

# 30. Winter Profile Example

Conceptual example:

```yaml
schedule:
  profiles:

    winter:
      windows:

        - name: overnight_circulation
          timing:
            type: fixed
            start: "22:00"
            end: "08:00"

          pump:
            speed: low

          booster:
            enabled: false

          allow_dosing: true

        - name: hydraulic_test
          timing:
            type: solar_anchor
            anchor: sunrise
            offset_minutes: 0
            duration_minutes: 10

          pump:
            speed: high

          booster:
            enabled: false

          allow_dosing: false
```

Again, exact operational values should be configured by the user.

---

# 31. Manual / Temporary Overrides

Temporary manual overrides must remain separate from profile definitions.

Examples:

```text
Run pump HIGH for 30 minutes
Run cleaner now
Pause dosing
Service mode
```

A temporary override should not rewrite the configured schedule.

After expiration:

```text
return to active schedule profile
```

Safety overrides remain higher priority than manual overrides.

---

# 32. Schedule Preview UI

Provide a schedule preview showing resolved concrete times.

This is particularly important because percentages of daylight are not intuitively obvious without resolution.

Example:

```text
Active profile: NORMAL

Today — Sep 22

Sunrise              07:16
Sunset               19:24
Daylight             12h 08m

01:00-02:00          Cleaner
06:03-08:29          Morning circulation
07:06-07:16          Hydraulic test
10:54-14:33          Daytime circulation
```

Prefer showing at least:

```text
today
tomorrow
```

and optionally the next 3 days.

This helps diagnose:

* seasonal movement
* DST transitions
* overlaps
* unexpected durations

---

# 33. Schedule Editor UI

The schedule editor should let the user choose timing type.

Conceptually:

```text
Timing type:

(*) Fixed time
( ) Sunrise/sunset relative
( ) Daylight fraction
```

For fixed:

```text
Start time
End time / duration
```

For solar anchor:

```text
Anchor
Offset minutes
Duration
```

For daylight fraction:

```text
Start %
End %
```

Display human-readable interpretation.

Example:

```text
Start: 30%
= approximately 10:54 today
```

---

# 34. Profile UI

Provide:

```text
Active profile:
[ Normal v ]
```

and profile management:

```text
Normal
Winter
Service
```

Actions may include:

```text
Activate
Rename
Duplicate
Delete
```

Protect the currently active/default profile from accidental deletion as appropriate.

---

# 35. Logging and Diagnostics

At minimum make the following inspectable for each scheduling day:

```text
local date
timezone
latitude/longitude source
sunrise
sunset
daylight duration
active schedule profile
resolved schedule windows
resolution warnings/errors
```

These do not necessarily need to become high-frequency sensor measurements.

Structured logs or daily schedule-history records may be sufficient.

This information will be useful when analyzing:

* FC demand
* circulation runtime
* filter tests
* seasonal behavior
* unexpected controller behavior

---

# 36. Schedule History

Consider preserving the resolved schedule actually used each day.

This is valuable because editing a profile later should not change historical interpretation.

Example:

```text
Sep 22:
profile = normal
daylight = 12h08m
resolved dosing windows = ...
```

Future FC/weather analysis can then compare actual dosing/circulation opportunity to demand.

---

# 37. Weather Integration

Solar scheduling should not require the weather forecast.

Sunrise/sunset are astronomical.

However, weather data continues to be collected independently.

Future architecture may use:

```text
astronomy:
    determines timing framework

weather forecast:
    modifies expected FC demand

actual weather:
    evaluates prediction error

FC measurements:
    close the loop
```

Keep these responsibilities separate.

---

# 38. UV and Solar Radiation

Do not assume:

```text
daylight_fraction == UV intensity
```

The scheduler aligns operations with the solar day.

The future FC model may separately use:

* UV
* shortwave radiation
* cloud cover
* water temperature
* daylight duration

to estimate chlorine demand.

This distinction is intentional.

---

# 39. Interaction With Canonical Water Temperature

Solar scheduling may produce seasonally adaptive circulation even without using temperature.

Do not make scheduler resolution dependent on water-temperature availability.

Temperature belongs to:

* freeze protection
* chemistry analysis
* future FC demand model

Profile selection may someday use temperature/forecast rules, but that is a separate feature.

---

# 40. Interaction With Freeze Protection

Freeze protection is always authoritative.

Example:

```text
Normal schedule says pump OFF.
Freeze protection says pump ON.
```

Result:

```text
pump ON
```

When freeze override clears:

```text
scheduler resumes the currently active profile
```

The scheduler should not attempt to "catch up" missed schedule runtime unless a future feature explicitly requests that behavior.

---

# 41. Interaction With SLAM Mode

Future SLAM mode may request enhanced circulation.

SLAM should use the existing override infrastructure rather than editing solar schedule profiles.

Priority conceptually:

```text
Safety
    >
SLAM/treatment temporary override
    >
manual temporary override
    >
active schedule profile
```

Exact priority between treatment/manual overrides should be defined when SLAM is implemented.

Solar scheduling should not duplicate SLAM circulation logic.

---

# 42. Configuration Validation

Validate schedule definitions before accepting them.

Examples:

Fixed:

```text
valid HH:MM local time
duration > 0
```

Solar anchor:

```text
valid anchor
finite offset
duration > 0
```

Daylight fraction:

```text
finite start/end fractions
end logically after start
```

Do not arbitrarily limit fractions to 0-1.

Protect against absurd values with a reasonable broad validation bound if desired.

Example:

```text
-2.0 ... +3.0
```

would already cover very large pre/post-daylight offsets.

Exact limits should follow implementation needs.

---

# 43. Conflict Validation

Warn or reject schedules that produce impossible actuator requests.

Examples:

```text
same moment:
pump OFF
and
pump HIGH
```

or:

```text
booster ON
while main pump explicitly OFF
```

Where merging is obvious:

```text
LOW overlapping HIGH -> HIGH
```

may be acceptable.

Where intent is ambiguous:

```text
reject/warn rather than silently guess
```

---

# 44. Schedule Resolution Invariants

The resolver should guarantee:

1. all output datetimes are timezone-aware
2. each resolved window has start < end
3. cross-midnight intervals resolve correctly
4. no duplicate execution from DST fall-back
5. nonexistent spring-forward times follow documented policy
6. solar times use correct local date/location
7. output order is deterministic
8. overlapping compatible windows are merged consistently
9. incompatible conflicts are surfaced
10. source profile/event identity remains traceable

---

# 45. Persistence and Restart

On application restart:

* reload active profile
* resolve the current local day's schedule
* determine whether the current time falls inside any active window
* resume correct scheduled state

Do not replay schedule events that occurred while the application was offline merely because their start time was missed.

Example:

```text
Cleaner event:
01:00-02:00

Pi boots:
02:30
```

Do not start the cleaner late unless catch-up behavior is explicitly designed in the future.

---

# 46. Changing Profile Mid-Day

If the user switches profiles during the day:

1. resolve the newly active profile immediately
2. determine desired current actuator state
3. transition through normal command/safety architecture
4. do not replay earlier events from the new profile
5. log the profile change

Example:

```text
13:00 switch Normal -> Winter
```

If Winter says pump should currently be OFF:

```text
normal scheduling requests OFF
```

subject to:

```text
SafetyGate / freeze overrides
```

---

# 47. Editing Active Profile Mid-Day

Changing the active profile configuration should similarly trigger re-resolution.

Do not require a restart merely to update schedule definitions if the current config system supports safe live application.

The UI should show:

```text
today's schedule updated
```

and the newly resolved remaining events.

---

# 48. Dosing Availability Calculations

Daily chlorine planning must use the resolved schedule.

For each local day calculate:

```text
total dosing-eligible duration
```

after applying:

* active profile
* resolved solar/fixed windows
* `allow_dosing`
* pump continuous-run first exclusion
* pump continuous-run last exclusion
* any other planning-level availability constraints

The FC controller should therefore automatically adapt daily duty calculation as solar windows grow/shrink.

---

# 49. Runtime Versus Planned Availability

Distinguish:

```text
planned dosing availability
```

from:

```text
actual delivered opportunity
```

Actual runtime may differ due to:

* freeze overrides
* safety faults
* manual overrides
* pump faults
* low tank
* application downtime

Do not pretend planned window duration equals actual delivered circulation/dosing time.

Actual actuator history remains authoritative for chlorine-delivery accounting.

---

# 50. Seasonal Analysis

This scheduling system should make later analysis possible.

Useful daily data:

```text
daylight length
scheduled pump runtime
actual pump runtime
scheduled dosing-eligible minutes
actual dosing minutes
FC demand
UV
shortwave
water temperature
weather
```

Future analysis can determine whether:

* daylight-scaled circulation is sufficient
* winter schedule is excessive
* summer runtime should be increased/decreased
* FC demand correlates more strongly with UV than daylight duration

Do not prematurely automate those conclusions in the first implementation.

---

# 51. Example Resolution

Assume:

```text
sunrise = 07:00
sunset  = 19:00
daylight length = 12h
```

Definitions:

```text
A:
daylight_fraction
-10% -> +10%

B:
daylight_fraction
30% -> 60%

C:
solar_anchor sunrise
offset -10 min
duration 10 min

D:
fixed
01:00
duration 60 min
```

Resolve:

```text
A:
05:48 -> 08:12

B:
10:36 -> 14:12

C:
06:50 -> 07:00

D:
01:00 -> 02:00
```

If the same profile is resolved during a 15-hour summer day, A and B automatically become longer intervals.

---

# 52. UI Explanation of Daylight Fractions

Provide concise help text:

```text
0% = sunrise
50% = midpoint between sunrise and sunset
100% = sunset

Negative values occur before sunrise.
Values above 100% occur after sunset.

Example:
-10% to 10%
runs across sunrise with a total duration equal to
20% of that day's daylight length.
```

This should prevent percentage scheduling from feeling opaque.

---

# 53. Recommended Initial Implementation Scope

First implementation should include:

* fixed timing
* solar-anchor timing
* daylight-fraction timing
* normal/winter named profiles
* manual active-profile selection
* local astronomy calculation
* daily resolver
* cross-midnight support
* DST-safe behavior
* schedule preview
* interaction with existing dosing availability
* continuous-pump-run identification
* config/UI/tests/docs

Do not initially implement:

* automatic seasonal profile selection
* forecast-based profile switching
* ML schedule optimization
* weather-dependent runtime modification
* autonomous pump-runtime optimization
* automatic filter-test scheduling outside normal schedule definitions

---

# 54. Recommended Implementation Phases

## Phase 1 — Resolver model

Implement:

* timing-type domain/config models
* fixed resolver
* solar-anchor resolver
* daylight-fraction resolver
* timezone/location handling
* unit tests

No actuator changes yet.

---

## Phase 2 — Profiles

Implement:

* named profiles
* active profile
* manual switching
* config persistence
* schedule preview

---

## Phase 3 — Runtime integration

Connect resolved windows to the existing scheduler.

Preserve:

* actuator safety
* pump speed handling
* booster interlock
* `allow_dosing`

---

## Phase 4 — Continuous-run reasoning

Integrate:

* cross-midnight runs
* speed transitions
* `no_dose_first_minutes`
* `no_dose_last_minutes`

---

## Phase 5 — Web editor

Add:

* timing-type selection
* percentage inputs
* solar-anchor inputs
* profile controls
* multi-day preview

---

## Phase 6 — Historical/diagnostic logging

Expose:

* daily sunrise/sunset
* daylight length
* active profile
* resolved windows

---

# 55. Testing Requirements

When implemented, test at minimum:

## Fixed schedules

* same-day fixed interval
* cross-midnight interval
* duration-based interval
* fixed event before/after midnight

## Solar anchors

* sunrise anchor
* sunset anchor
* positive offset
* negative offset
* fixed duration

## Daylight fraction

* 0%
* 50%
* 100%
* negative fraction
* > 100%
* summer long day
* winter short day

## DST

* spring-forward nonexistent fixed time
* fall-back ambiguous fixed time executes once
* solar event follows actual sunrise correctly across DST transition

## Profiles

* normal profile resolution
* winter profile resolution
* profile switching mid-day
* profile persistence across restart

## Continuous pump runs

* LOW -> HIGH does not break continuous run
* HIGH -> LOW does not break continuous run
* `allow_dosing` true -> false does not break continuous run
* midnight does not break cross-midnight run

## Dosing

* first exclusion based on actual pump start
* last exclusion based on actual pump stop
* allow_dosing sub-window respected
* seasonal duration changes alter available dosing minutes correctly

## Conflicts

* compatible overlapping pump windows
* incompatible actuator commands
* booster without pump
* duplicate event definitions

## Location/timezone

* missing location with solar event
* invalid timezone
* coordinate update causes re-resolution

## Restart

* restart inside active window
* restart after completed event
* no unintended catch-up execution

---

# 56. Documentation Requirements

When implemented, update:

* README
* AGENTS.md
* schedule/config documentation
* web UI help
* deployment/local-config guidance

Document:

* timing modes
* fraction semantics
* DST behavior
* cross-midnight behavior
* schedule-profile priority
* freeze protection priority
* relationship to chlorine control
* relationship to weather/UV data
* required site location/timezone

---

# 57. Core Implementation Rule for Codex

When asked to implement this feature:

Do **not** rewrite downstream control services around astronomy.

The preferred architecture is:

```text
abstract schedule
        |
        v
daily resolver
        |
        v
ordinary concrete schedule windows
        |
        v
existing runtime/control architecture
```

Before implementation:

1. inspect the current scheduler
2. identify the smallest domain/config additions
3. identify how continuous pump runs are currently represented
4. identify how chlorine eligibility is calculated
5. identify how profile/config state is persisted
6. propose migration of current fixed schedules
7. implement in phases

Avoid one giant scheduler rewrite if the feature can be introduced incrementally.

---

# 58. Summary of Intended User Experience

The user creates:

```text
NORMAL profile
```

with:

```text
Cleaner:
01:00-02:00

Hydraulic check:
10 minutes before sunrise for 10 minutes

Morning circulation:
-10% to +10% daylight

Daytime circulation/dosing:
30% to 60% daylight
```

Every day the controller calculates sunrise and sunset.

In summer:

```text
daylight is longer
circulation/dosing windows become longer
```

In winter:

```text
daylight is shorter
circulation/dosing windows become shorter
```

When DST changes:

```text
solar-relative events remain aligned with sunlight
fixed events remain aligned with wall-clock time
```

The user may switch to:

```text
WINTER profile
```

where normal circulation occurs overnight.

Regardless of selected profile:

```text
freeze protection remains authoritative
```

The UI always shows the resolved concrete schedule for today and upcoming days.

The chemistry controller continues to determine chlorine quantity independently from scheduling.

The resulting system adapts naturally to:

* DST
* seasonal sunrise/sunset changes
* changing daylight duration

without confusing solar scheduling with actual chlorine-demand modeling.
