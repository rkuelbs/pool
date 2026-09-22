# Automated SLAM / High-Chlorine Treatment Mode

## Status

Future feature specification.

Do **not** implement this feature merely because this file exists. This document describes the intended behavior and architecture for a future implementation of automated or semi-automated SLAM/high-chlorine treatment.

Before implementing, inspect the current repository architecture, configuration, safety logic, FC-demand estimator, chlorination controller, notification system, database schema, and web UI. Adapt this design to the current code rather than preserving obsolete APIs or names from the date this document was written.

---

# 1. Purpose

The normal pool controller is designed to maintain a tightly controlled daily free-chlorine level during healthy pool operation.

SLAM mode serves a different purpose:

* recover from algae
* respond to persistent abnormal chlorine demand
* treat persistent combined chlorine
* perform a high-chlorine cleanup treatment
* maintain a commanded elevated FC target during treatment
* minimize manual chlorine additions and repeated calculations
* guide the operator through FC/CC testing
* automate treatment dosing where enough recent measurement data exists
* prevent abnormal treatment demand from corrupting the normal FC-demand estimator
* automatically transition back to normal operation after successful treatment

SLAM mode should reuse existing infrastructure wherever possible:

* FC observations
* manual chemical-addition logging
* chlorine pump calibration
* chlorine delivery accounting
* SafetyGate
* circulation pump control
* ChlorinationController / relay pulse logic
* chlorine-tank estimation
* notifications / Pushover
* history database
* web UI
* normal FC-demand configuration

SLAM should be an additional high-level control mode, not an independent hardware-control implementation.

---

# 2. Fundamental Design Principle

Normal FC demand and SLAM FC demand are fundamentally different quantities.

The normal estimator answers:

> How much chlorine does a healthy pool normally consume under ordinary operating conditions?

The SLAM estimator answers:

> How quickly is the current abnormal treatment demand consuming elevated chlorine right now?

These must remain separate.

## Critical invariant

**No FC observation interval occurring from entry into SLAM until completion of post-SLAM recovery may update the normal FC-demand estimator.**

The normal learned baseline must be frozen when SLAM begins.

It must remain unchanged throughout:

* initial SLAM charge
* treatment
* SLAM maintenance
* FC retesting
* overnight chlorine-loss testing
* recovery from elevated FC

Normal demand learning resumes only after the pool has returned to its normal FC operating region and a new clean normal-reference baseline has been established.

---

# 3. Relationship to Normal FC Control

The normal controller may have a typical operating target such as:

```text
Normal target FC: 4.25 ppm
Normal operating band: approximately 4.0-4.5 ppm
```

Those values are examples and remain normal FC configuration rather than SLAM configuration.

Normal operation uses the existing slow adaptive demand estimator, which may include:

* recent reference FC observations
* actual chlorine delivered
* manual chlorine additions
* weighted recent demand
* rate-limited adaptation
* target feedback
* future weather adjustment

SLAM mode temporarily suspends that learning process.

When SLAM begins:

```text
normal_baseline_demand = frozen current value
normal demand learning = disabled
normal feedback correction = disabled
```

The value is retained so it can be restored during recovery.

---

# 4. High-Level State Machine

Use an explicit treatment state machine.

Conceptually:

```text
NORMAL
  |
  | operator starts treatment
  v
SLAM_INITIAL_CHARGE
  |
  v
SLAM_VERIFY_TARGET
  |
  v
SLAM_MAINTAIN
  |
  +------> SLAM_RETEST_DUE
  |             |
  |             v
  |       SLAM_MAINTAIN
  |
  +------> SLAM_OCLT
  |             |
  |             | fail
  |             v
  |       SLAM_MAINTAIN
  |
  | OCLT pass + CC pass + clarity confirmed
  v
RECOVERY
  |
  | FC returns to normal region
  v
NORMAL_REBASE
  |
  | first valid normal-to-normal interval
  v
NORMAL
```

Exact class/enum names should follow the architecture that exists when the feature is implemented.

Possible states:

* `normal`
* `slam_initial_charge`
* `slam_verify_target`
* `slam_maintain`
* `slam_retest_due`
* `slam_oclt`
* `recovery`
* `normal_rebase`
* `aborted`

There must always be a clearly exposed:

```text
ABORT TREATMENT
```

action.

Aborting treatment must stop automatic high-FC dosing immediately while retaining any safe circulation required by current safety/runtime architecture.

---

# 5. Starting SLAM

SLAM must always be explicitly initiated by the operator.

Normal FC logic should never autonomously decide to begin SLAM.

The UI should provide a workflow similar to:

```text
Start SLAM Treatment
```

The operator should provide or confirm:

* current FC
* current CC
* current CYA
* desired SLAM FC target
* whether initial chlorine will be:

  * dosed automatically
  * added manually
  * split between manual and automatic addition

The application may calculate or suggest a treatment target from CYA if a validated target table/model exists at implementation time, but the operator should confirm the final commanded target.

Example:

```text
Current FC:     4.3 ppm
Current CC:     0.8 ppm
CYA:           50 ppm

Suggested SLAM target: 20 ppm

[ Confirm 20 ppm ]
```

Do not silently select an aggressive treatment target without user acknowledgement.

---

# 6. Initial Chlorine Requirement

Calculate the initial required FC increase:

```text
required_fc_increase =
    slam_target_fc - current_fc
```

Convert that into chlorine quantity using the controller's current chlorine conversion/calibration model.

Do not create a second independent chlorine-volume calculation if one already exists.

Example:

```text
Current FC       4.3 ppm
Target FC       20.0 ppm
Required rise   15.7 ppm

Estimated chlorine required:
268 fl oz
```

---

# 7. Initial Dose: Manual, Automatic, or Hybrid

The system should support three workflows.

## 7.1 Fully automatic

The chlorine dosing system delivers the initial calculated quantity.

This is appropriate only if:

* chlorine pump calibration is trusted
* chlorine tank contains enough chemical
* automatic dose limits permit it
* circulation and pressure safety are satisfied

## 7.2 Manual initial addition

The operator physically adds liquid chlorine and records the actual amount.

Example:

```text
Required treatment dose: 268 oz

Operator:
Added 256 oz manually
```

The manual chemical addition must be logged as:

```text
treatment / SLAM chlorine
```

rather than an ordinary normal-operation chlorine addition.

The controller then accounts for that addition when predicting current FC.

## 7.3 Hybrid

For a large initial dose, this may be the preferred workflow.

Example:

```text
Required: 268 oz

Recommended:
Add 2 gallons manually.
Allow circulation/mixing.
The controller will trim the remaining dose after retesting.
```

A future configuration could limit the maximum single automatic initial treatment addition:

```yaml
slam:
  max_initial_automatic_chlorine_oz: ...
```

Large treatment additions should not require running the normal low-rate dosing pump for an unnecessarily long period if manual addition is easier.

---

# 8. Initial Mixing and Verification

Do not assume that an open-loop calculated initial dose has perfectly achieved the target.

Sources of error include:

* pool-volume estimate
* chlorine concentration
* chlorine age/degradation
* chlorine pump calibration
* manual-addition measurement
* incomplete mixing
* abnormal chlorine consumption during treatment

After the initial addition, require a verification FC measurement after an appropriate mixing interval.

Conceptually:

```text
Initial dose complete
        |
        v
Circulate 30-60 minutes
        |
        v
Enter FC measurement
```

The exact interval should be configurable or easily changed.

Example:

```text
Target FC:     20.0
Measured FC:   17.8
Difference:     2.2 ppm
```

The controller may then calculate and deliver a trim dose.

The initial verification measurement becomes the first reliable FC anchor for SLAM maintenance.

---

# 9. Temporary SLAM Demand Estimator

Once reliable FC measurements exist during treatment, create a temporary treatment-demand estimator.

For two FC observations:

```text
FC_start
FC_end
```

and known chlorine additions during the interval:

```text
FC_added
```

calculate:

```text
FC_consumed =
    FC_start
    + FC_added
    - FC_end
```

Then:

```text
slam_demand_ppm_per_hour =
    FC_consumed / elapsed_hours
```

or equivalently:

```text
slam_demand_ppm_per_day =
    FC_consumed / elapsed_days
```

Example:

```text
08:00 FC = 20.0 ppm

Equivalent chlorine added during interval:
4.0 ppm

12:00 FC = 21.0 ppm

Consumed:
20 + 4 - 21 = 3 ppm

Over four hours:
0.75 ppm/hour

Equivalent:
18 ppm/day
```

That is treatment demand.

It must never become a normal-demand observation.

---

# 10. SLAM Demand Learning Behavior

SLAM demand changes much faster than normal pool demand.

As algae/organic load is oxidized, treatment demand should normally decline.

Therefore, the SLAM estimator should adapt rapidly.

A reasonable initial design is to use the most recent 2-3 valid treatment observations.

For example:

```text
newest:      60%
previous:    25%
third:       15%
```

This is only an initial proposed weighting.

The implementation should make the weighting configurable or easy to revise if practical.

The key behavior is:

* short memory
* heavy weighting toward recent demand
* no long-term rate-limit intended for normal seasonal learning
* no persistence across unrelated SLAM events

When treatment ends:

```text
slam demand estimate = discarded
```

A future SLAM starts with no assumption that its abnormal demand matches the previous event.

---

# 11. Treatment Feed-Forward Dosing

Once the controller has a reliable treatment-demand estimate, it may use that estimate to maintain the SLAM target between manual FC measurements.

Example:

```text
Current FC:           20.2 ppm
SLAM target:          20.0 ppm
Estimated demand:     12 ppm/day
```

Equivalent hourly consumption:

```text
12 / 24 = 0.5 ppm/hour
```

The treatment controller may distribute chlorine during available circulation periods to approximately replace that consumption.

This is analogous to normal feed-forward dosing, but SLAM mode requires stricter limits because its demand estimate is temporary and may change rapidly.

---

# 12. Measurement-Age Safety

The controller does not have a direct continuous FC sensor.

Therefore SLAM must not continue aggressive automatic dosing indefinitely from an old manual FC measurement.

Track:

```text
last_slam_fc_test_at
slam_fc_measurement_age
```

Automatic SLAM dosing should become progressively more conservative as the latest FC observation ages.

A conceptual policy:

```text
fresh FC observation:
    full SLAM feed-forward permitted

moderately stale:
    reduced/conservative treatment dosing

too stale:
    automatic treatment dosing suspended
    FC test required
```

Example initial values might eventually be:

```text
< 6 hours:
    normal automatic SLAM maintenance

6-12 hours:
    conservative/reduced maintenance

> 12 hours:
    suspend automatic SLAM dosing
    request FC retest
```

Do not hard-code these exact values merely because they appear in this design document.

They should be configurable and should be validated during implementation.

---

# 13. Dose Safety Limits

SLAM mode must remain fully subject to existing SafetyGate behavior.

It must never bypass:

* circulation pump requirement
* pump stabilization requirement
* pump-output pressure safety
* chlorine tank inhibit/re-enable hysteresis
* timed relay safety
* actuator reconciliation
* startup-safe behavior
* other applicable safety rules

SLAM should add additional treatment-specific limits such as:

```text
maximum automatic chlorine since last FC measurement
maximum treatment dose per hour
maximum treatment dose per control cycle
maximum single automatic initial addition
maximum FC-measurement age
```

If a safety limit prevents dosing, treatment status must explicitly say why.

Do not count rejected chlorine runtime as delivered chlorine.

---

# 14. Recommended FC Retest Schedule

Do not assume a fixed 12-hour test interval throughout the entire SLAM.

Treatment demand is usually highest and least predictable near the beginning.

The controller should recommend more frequent testing initially and relax the interval as treatment stabilizes.

Possible behavior:

## Initial charge

```text
Retest FC after approximately 30-60 minutes of circulation.
```

## Early active treatment

```text
Recommend FC retest approximately every 3-4 hours.
```

## Falling/stable demand

```text
Recommend approximately every 6 hours.
```

## Near completion

```text
8-12 hours may be acceptable.
```

The recommended interval should ideally depend on:

* estimated treatment demand
* FC measurement age
* stability of recent treatment-demand estimates
* magnitude of automatic dosing since the last test
* how close the pool is to completion criteria

The UI should display:

```text
Next FC/CC test recommended:
3 h 20 min
```

Use the existing notification system to send reminders.

Example:

```text
SLAM FC retest due.
Please test FC and CC and enter the results.
```

---

# 15. SLAM FC Observations

Treatment FC measurements should be stored using normal historical measurement infrastructure but clearly classified as treatment observations.

A conceptual observation might include:

```text
measured_at
fc_ppm
cc_ppm
source
treatment_id
treatment_phase
```

Do not create duplicate FC-history storage if the existing `FcObservation` model can be cleanly extended.

Potential treatment source remains:

```text
manual_dpd
```

The key distinction is not necessarily sensor source; it is that the observation occurred during a treatment interval.

---

# 16. Treatment Session

A complete SLAM should have a persistent treatment/session identity.

Conceptually:

```text
SlamTreatment
```

with fields such as:

```text
id
started_at
ended_at
state
target_fc_ppm
cya_ppm
starting_fc_ppm
starting_cc_ppm

normal_baseline_demand_at_start

latest_fc_ppm
latest_cc_ppm
latest_fc_test_at

estimated_slam_demand_ppm_per_day

automatic_chlorine_oz
manual_chlorine_oz

status
completion_reason
```

Do not assume these exact persistence classes or schema fields; fit them to the current database architecture.

A persistent treatment ID makes later analysis possible:

```text
SLAM 2026-07-18
Duration: 38 hours
Manual chlorine: 256 oz
Automatic chlorine: 173 oz
Initial demand: 17 ppm/day
Final demand: 2.8 ppm/day
OCLT loss: 0.6 ppm
```

---

# 17. Combined Chlorine

SLAM UI should ask for CC whenever the operator performs an FC treatment test when practical.

Track:

```text
FC
CC
```

separately.

Combined chlorine is part of the completion decision but should not drive an uncontrolled automatic chlorine-dose formula by itself.

The software should display CC trend during the treatment.

Example:

```text
CC history:

0.9
0.7
0.4
0.2
0.0
```

---

# 18. OCLT Mode

Provide an integrated Overnight Chlorine Loss Test workflow.

Possible action:

```text
Start OCLT
```

The controller should guide the user through:

## Evening

After sunlight is no longer materially affecting FC:

```text
Test FC
Test CC
Enter results
```

Record:

```text
oclt_start_fc
oclt_start_cc
oclt_start_time
```

Then:

```text
suspend automatic chlorine dosing
```

for the OCLT interval.

The circulation pump may continue according to whatever circulation behavior is appropriate.

## Morning

Before significant sunlight:

Send a notification:

```text
OCLT morning FC test due.
```

Operator enters:

```text
morning FC
morning CC
```

Calculate:

```text
overnight_fc_loss =
    evening_fc - morning_fc
```

Do not subtract automatic chlorine because automatic chlorine must be suspended during the OCLT.

Display the result clearly.

Example:

```text
Evening FC:        18.4
Morning FC:        17.8
Overnight loss:     0.6

CC:                 0.0
```

---

# 19. SLAM Completion Criteria

Treatment completion should require explicit criteria rather than merely reaching the target FC.

Conceptually:

```text
OCLT passes
AND
CC criterion passes
AND
water clarity confirmed
```

The exact chemistry thresholds should live in configuration/design appropriate at implementation time rather than being permanently embedded only in prose.

A common conceptual OCLT completion threshold is:

```text
overnight FC loss <= approximately 1 ppm
```

and CC should be low.

Water clarity requires operator confirmation unless future hardware provides a trustworthy turbidity/clarity measurement.

UI:

```text
SLAM Completion

OCLT            PASS
Combined Cl     PASS
Water clear?    [ YES ] [ NO ]
```

Only after all criteria pass should the application recommend ending treatment.

The operator should explicitly confirm:

```text
Complete SLAM
```

---

# 20. Recovery Mode

Do not return directly from a SLAM target such as 20 ppm to normal 4.25 ppm control.

Enter a dedicated recovery state.

When treatment completes:

```text
normal learned demand remains frozen
slam demand estimate is discarded
automatic SLAM maintenance ends
```

If FC is substantially above the normal operating target:

```text
normal automatic chlorine dose = 0
```

Allow ordinary chlorine loss to bring FC downward.

Do not command "negative chlorine."

---

# 21. Recovery Catch Behavior

As FC approaches the normal target, use the frozen healthy-pool demand estimate to avoid overshooting below the target.

Conceptually:

```text
recovery_dose_ppm =
    max(
        0,
        normal_baseline_demand
        + normal_target_fc
        - measured_fc
    )
```

Example:

```text
Normal target:     4.25
Normal demand:     2.5 ppm/day
Measured evening:  6.0

Recovery dose:
2.5 + 4.25 - 6.0
= 0.75 ppm
```

This lets the normal controller begin "catching" the descending FC level without immediately resuming its normal feedback-learning behavior.

A damped implementation may ultimately be preferable; use the existing controller architecture and empirical behavior at implementation time.

---

# 22. Returning to Normal Demand Learning

Do not immediately use the first post-SLAM observation for normal learning.

Recommended sequence:

```text
SLAM complete
      |
      v
RECOVERY
      |
      | FC reaches normal operating region
      v
NORMAL_REBASE
      |
      | establish clean reference FC
      v
first normal-to-normal interval
      |
      v
resume normal demand learning
```

The first in-band reference FC after recovery becomes a new normal-demand baseline point.

Only the following clean reference-to-reference interval becomes eligible for the ordinary rolling demand estimator.

This prevents residual elevated-FC treatment dynamics from contaminating normal demand.

---

# 23. Manual Chlorine During SLAM

Every manual liquid-chlorine addition performed during SLAM must be recorded.

It should:

* contribute to SLAM mass balance
* contribute to treatment history
* NOT contribute to normal-demand learning

Example:

```text
Manual addition:
128 oz sodium hypochlorite
Treatment ID: 42
```

The controller should immediately incorporate the equivalent FC addition into its treatment accounting.

---

# 24. Manual Chlorine Outside SLAM

Future implementation should distinguish ordinary manual additions from treatment additions.

Possible classifications:

```text
normal_manual
treatment
slam
```

A large manual chlorine addition outside an active SLAM should preferably ask:

```text
Is this a treatment/shock addition?
```

If yes:

* prevent that reference interval from entering normal-demand learning
* possibly offer to begin a treatment/recovery session

Do not silently interpret every manual chlorine addition as SLAM.

---

# 25. Normal Demand Estimator During SLAM

The normal estimator should remain visible but frozen.

For example:

```text
Normal demand estimate:
2.7 ppm/day

Status:
Frozen during SLAM
```

Do not clear or overwrite the previous healthy-pool baseline.

The normal estimator should be able to survive:

* multi-day SLAM
* system restart
* application restart

without accidentally learning treatment demand.

Persistence should therefore make the treatment/recovery state explicit enough to restore the correct behavior after restart.

---

# 26. SLAM Demand Display

Expose treatment demand separately.

For example:

```text
SLAM target:             20.0 ppm
Latest FC:               19.1 ppm
Latest FC age:            2h 14m

Current SLAM demand:
0.42 ppm/hour
10.1 ppm/day equivalent

Normal frozen demand:
2.7 ppm/day
```

This reinforces that the two estimators are separate.

---

# 27. Treatment Dashboard

SLAM mode should have a dedicated dashboard/card rather than overloading the normal FC card.

Suggested information:

```text
SLAM ACTIVE

Target FC             20.0
Latest FC             19.1
Latest CC              0.4
FC test age            2h 14m

Estimated SLAM demand
0.42 ppm/hr
10.1 ppm/day

Normal demand
2.7 ppm/day (frozen)

Next FC test
1h 46m

Automatic chlorine
Active

Treatment duration
18h 32m
```

Controls:

```text
[ Enter FC / CC Test ]
[ Log Manual Chlorine ]
[ Start OCLT ]
[ Pause Auto Dosing ]
[ Abort SLAM ]
```

Require confirmation for destructive/important actions such as aborting or completing treatment.

---

# 28. Notifications

Reuse the existing notification/Pushover infrastructure.

Do not implement a separate SLAM notification system.

Potential notifications include:

## Retest

```text
SLAM FC retest due.
Current estimate is based on a 4-hour-old FC measurement.
```

## Stale FC

```text
SLAM automatic dosing suspended.
FC test required before further automatic treatment dosing.
```

## Low chlorine tank

Reuse existing tank-safety warning/inhibit behavior.

## OCLT

```text
OCLT evening FC/CC test required.
```

and:

```text
OCLT morning FC test due before significant sunlight.
```

## Completion

```text
SLAM completion criteria appear satisfied.
Review results and confirm treatment completion.
```

Use existing throttling to prevent notification spam.

---

# 29. Automatic Treatment Dosing Must Remain Conservative

Because FC is manually measured, treatment automation is inherently model-based between tests.

Therefore:

* do not chase the exact target aggressively from old data
* do not continue dosing indefinitely from stale FC
* cap automatic amount between tests
* request manual verification after large additions
* prefer slightly low treatment prediction over uncontrolled overshoot
* retain all existing chlorine safety limits

The goal is:

> minimize manual intervention while still requiring enough FC measurements to keep the treatment bounded and observable.

It is **not**:

> run an unattended multi-day chemical treatment with no FC verification.

---

# 30. Weather During SLAM

Do not use the normal weather-demand model to learn SLAM demand initially.

Actual treatment-demand observations inherently include whatever solar/environmental loss occurred between FC tests.

For the first implementation:

```text
SLAM demand = empirically observed treatment consumption
```

Do not attempt to separately learn:

```text
organic treatment demand
+
UV demand
+
temperature adjustment
```

unless future data shows a clear benefit.

Continue logging all weather data normally.

That information may be useful for later analysis.

---

# 31. ORP

Do not use ORP as the SLAM FC controller.

ORP may continue to be:

* logged
* graphed
* displayed diagnostically
* analyzed after the fact

It must not substitute for FC testing.

At high FC levels and changing chemistry, ORP behavior may be particularly unsuitable as an FC estimator.

---

# 32. pH During SLAM

High FC levels can interfere with some phenol-red pH testing methods.

The application should avoid using a potentially unreliable high-FC manual pH reading as an automatic treatment-control input without accounting for that limitation.

Existing automated pH sensor behavior should remain available for diagnostics.

Do not introduce automatic acid dosing solely as part of initial SLAM implementation.

SLAM mode should primarily control chlorine.

---

# 33. Pump / Circulation

SLAM may need stronger circulation behavior than normal operation, but do not create a second pump-control stack.

Reuse normal scheduler/override infrastructure.

Treatment mode may request:

```text
enhanced circulation
```

or a configurable temporary circulation override.

Any treatment circulation override should:

* remain subject to SafetyGate
* survive application restart if the treatment session is persistent
* clearly display why the pump is running
* release automatically when treatment/recovery no longer requires it

Do not automatically run the booster/cleaner solely because SLAM is active unless explicitly configured.

---

# 34. Restart / Crash Recovery

SLAM is a multi-hour or multi-day process.

Its state must survive:

* application restart
* Pi reboot
* web-server restart

After restart the controller must know:

* whether treatment was active
* current phase
* target FC
* latest FC observation
* latest CC
* last FC test time
* treatment demand estimate or the observations needed to reconstruct it
* automatic dosing status
* amount automatically dosed
* amount manually logged
* whether OCLT was active
* whether the normal estimator is frozen

Fail safe after an ambiguous restart.

Do not resume aggressive automatic SLAM dosing if treatment state cannot be reconstructed reliably.

Instead:

```text
SLAM requires FC verification after restart.
```

---

# 35. Treatment History

Treatment sessions should remain available for later analysis.

Useful historical outputs:

* start/end time
* duration
* starting FC/CC
* target FC
* CYA
* chlorine used manually
* chlorine used automatically
* total chlorine
* treatment-demand observations
* peak estimated demand
* final estimated demand
* FC/CC test timeline
* OCLT results
* completion criteria
* abort reason if applicable

This may eventually help tune treatment behavior.

---

# 36. Configuration

Exact configuration should follow current project conventions.

Possible conceptual configuration:

```yaml
slam:
  enabled: true

  initial_mix_minutes: 45

  max_initial_automatic_chlorine_oz: null

  demand:
    observation_count: 3
    observation_weights:
      - 0.60
      - 0.25
      - 0.15

  testing:
    initial_retest_minutes: 45
    early_retest_hours: 4
    stable_retest_hours: 6
    maximum_fc_age_hours: 12

  dosing:
    max_automatic_oz_per_hour: null
    max_automatic_oz_since_last_fc_test: null

  recovery:
    normal_band_margin_ppm: ...
```

These exact keys/defaults are NOT mandatory.

Do not invent arbitrary safety limits during implementation without discussing them.

---

# 37. Safety Invariants

Regardless of treatment state:

1. SafetyGate remains the final authority on actuator commands.
2. Chlorine cannot dose without valid circulation conditions.
3. Chlorine tank inhibit/hysteresis remains enforced.
4. Rejected pulses are never counted as delivered.
5. Hardware timed-OFF behavior remains intact.
6. SLAM never bypasses normal actuator safety.
7. Stale FC eventually stops automatic treatment dosing.
8. Application restart must not cause an uncontrolled treatment dose.
9. Normal FC-demand learning remains frozen until recovery is complete.
10. Manual treatment additions are included in SLAM mass balance.

---

# 38. Non-Goals for First Implementation

Do NOT make the first version unnecessarily complex.

Do not initially implement:

* autonomous algae detection
* autonomous decision to enter SLAM
* ORP-based FC estimation
* camera-based water-clarity detection
* weather-corrected SLAM demand
* automatic pH/acid treatment during SLAM
* persistent learned SLAM behavior between unrelated treatment events
* machine learning
* unattended multi-day treatment without manual FC tests

The first implementation should be understandable from the code and UI.

---

# 39. Recommended Implementation Order

When this feature is eventually implemented, do it incrementally.

## Phase 1 — Treatment session and learning isolation

Implement:

* SLAM session
* state machine
* freeze normal demand learning
* treatment-tagged FC tests
* treatment-tagged chlorine additions
* history
* manual start/abort/complete

No automatic treatment dosing yet.

## Phase 2 — Initial dose helper

Implement:

* target calculation/entry
* required chlorine calculation
* manual/automatic/hybrid initial charge
* mixing timer
* verification test

## Phase 3 — SLAM demand estimator

Implement:

* treatment observations
* fast weighted demand estimator
* display only

Observe real data before trusting it for control.

## Phase 4 — Automatic SLAM maintenance

Implement:

* feed-forward replacement dosing
* stale FC limits
* per-hour / per-test dose caps
* retest reminders

## Phase 5 — OCLT workflow

Implement:

* evening measurement
* automatic-dose suspension
* morning reminder
* pass/fail calculation
* completion checklist

## Phase 6 — Recovery

Implement:

* zero dosing at high post-SLAM FC
* frozen normal baseline usage
* recovery catch dosing
* normal rebase
* resume normal learning

This staged approach is preferred over implementing the entire feature in one Codex task.

---

# 40. Tests Required

When implemented, tests should cover at minimum:

## State transitions

* NORMAL -> initial charge
* initial charge -> verify
* verify -> maintain
* maintain -> retest due
* maintain -> OCLT
* OCLT fail -> maintain
* OCLT pass -> recovery after completion confirmation
* recovery -> normal rebase
* normal rebase -> normal
* abort from every treatment state

## Normal estimator isolation

* no treatment FC interval updates normal baseline
* no recovery interval updates normal baseline
* pre-SLAM normal baseline survives entire treatment
* first post-recovery normal-to-normal interval resumes learning

## Treatment mass balance

* manual chlorine included
* automatic chlorine included
* rejected chlorine excluded
* correct elapsed-time normalization
* multiple additions between tests

## Demand estimator

* newest observations weighted most heavily
* fewer than three observations renormalize correctly
* invalid observations excluded
* estimator discarded after treatment

## Initial dose

* fully automatic
* fully manual
* hybrid
* verification trim
* large automatic amount limit

## Measurement age

* fresh FC allows maintenance
* stale FC reduces/blocks dosing as configured
* new FC measurement restores maintenance

## Dose limits

* per-hour cap
* since-last-test cap
* tank inhibit
* circulation safety
* pressure safety

## OCLT

* automatic dosing suspended
* evening/morning FC stored
* loss calculated correctly
* pass/fail criteria
* no sunlight/dose compensation accidentally applied

## Recovery

* elevated FC produces zero chlorine
* descending FC eventually receives catch dose
* no negative dose
* no normal learning until rebase

## Persistence

* restart during maintain
* restart during OCLT
* restart during recovery
* ambiguous state requires FC verification before automatic dosing resumes

---

# 41. Documentation Requirements

When implementation begins, update:

* README
* AGENTS.md
* configuration documentation
* web UI help text
* database/history documentation
* safety documentation

Explain clearly:

* normal FC mode and SLAM mode use different demand estimators
* SLAM demand is temporary
* manual FC testing remains required
* normal baseline is frozen
* automatic dosing stops when FC information becomes too stale
* OCLT suspends automatic chlorine addition
* recovery does not immediately resume normal learning

---

# 42. Core Implementation Rule for Codex

When eventually asked to implement this specification:

**Do not simply create a large new standalone "SLAM controller" that duplicates existing services.**

Reuse:

* SafetyGate
* CommandRouter
* ChlorinationController
* chlorine delivery accounting
* FC observation storage
* notifications
* pump overrides
* database infrastructure
* existing web patterns

SLAM should primarily be an orchestration/state/estimation layer above the existing safe actuator architecture.

Before writing code:

1. inspect the current architecture
2. map each requirement here to an existing service or identify the smallest required new service
3. identify schema changes
4. identify restart/persistence behavior
5. identify safety boundaries
6. identify normal-demand-learning isolation
7. propose implementation phases

Do not start with a large monolithic patch.

---

# 43. Summary of Intended User Experience

Normal pool:

```text
FC controller maintains normal target automatically.
```

Problem discovered:

```text
Operator selects Start SLAM.
```

System:

```text
Enter FC / CC / CYA.
Confirm treatment target.
```

Large initial dose:

```text
System recommends manual/automatic/hybrid dose.
```

Operator adds chlorine or controller doses.

System:

```text
Circulate.
Retest FC in 45 minutes.
```

Operator tests.

System:

```text
Target verified.
SLAM maintenance active.
Estimated treatment demand: 14 ppm/day.
Next FC test in 4 hours.
```

Controller replaces estimated chlorine loss between tests.

As demand falls:

```text
Estimated demand: 7 ppm/day.
Next test in 6 hours.
```

Near completion:

```text
Run OCLT tonight?
```

Operator starts OCLT.

System suspends treatment dosing overnight.

Morning:

```text
Enter FC / CC.
```

System:

```text
OCLT PASS
CC PASS
Confirm water is clear.
```

Operator confirms.

System:

```text
SLAM complete.
Recovery mode active.
Automatic chlorine paused while FC falls toward normal target.
```

FC falls toward normal range.

System uses the frozen healthy-pool demand to catch the descending FC level.

Then:

```text
Normal FC baseline re-established.
Normal demand learning resumed.
```

Throughout the process, treatment demand never contaminates the healthy-pool demand model.
