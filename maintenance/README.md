# Home Assistant maintenance — September 12, 2026

## Applied

- Battery Notes 3.6.3 installed through HACS. 34 discovered device notes configured from its battery library; existing battery entities remain visible. Initial replacement dates are seeded by Battery Notes from HA device creation dates, not verified replacement history. Use each device’s Battery replaced button after a real replacement.
- `../battery-warning.yaml`: native lists fix the JSON conversion failure; one persistent notification per severity; clears when no matching low batteries remain; charging exclusion; device/entity/area exclusions; `Awaiting setup` label exclusion; Battery Notes types and replacement/threshold events.
- Appliance alarms retain existing thresholds and phone/local alerts. Persistent date/time helpers track pending conditions and sent alerts, checked every minute and on sensor changes. Unknown readings preserve pending heat/power timers; valid readings are required to clear them. The elapsed time across downtime is treated conservatively because HA cannot observe conditions while stopped.
- Managed local backups: daily at 03:00 America/Chicago, 14 copies, all add-ons plus configuration, database, media, share, SSL and local add-ons. Local encryption remains off, matching existing backups. Legacy `automation.automatic_backups` is disabled. A health notification flags failure, missing success status, or a successful backup older than 36 hours.
- Unused `Weather Forecast Display` template removed after checking configuration, dashboards and ESPHome references.

## Inventory without deleting devices

Apply the `Awaiting setup` label to stored or not-yet-installed **devices** in Settings → Devices & services → Devices. Their registry records, names, and areas remain available as inventory; the battery notification excludes them. Filter the Devices page by this label to see the setup backlog. No devices were automatically classified, disabled, or removed.

Known plans: office Inovelli fan switch awaiting installation; outdoor lighting design undecided beyond the sauna strip.

## Deferred

- **NAS/off-machine backups:** add a NAS destination when it is online, run a backup there, and verify recovery. Current backups are local only.
- Keep 60-day recorder retention; storage is not currently a concern.
- Battery Notes' initial replacement dates are baselines. Confirm device battery types physically when changing batteries.

## Source and validation

`appliance-alarms.yaml` and `backup-health.yaml` contain the corresponding entries from `/Volumes/config/automations.yaml`; they are reference copies, not additional includes. `appliance-alarm-timers.yaml` corresponds to `/Volumes/config/appliance_alarm_timers.yaml`, included by `configuration.yaml`.

Run `python3 maintenance/test-appliance-alarms.py` from the repository root (requires PyYAML and Jinja2). It simulates restart, dwell reset, reminders, recovery, power loss, and unavailable readings without sending notifications or controlling devices. HA configuration validation and live traces provide the integration checks. Active appliance timestamps were also verified across a real HA restart.

Verified on 2026-09-12: HA config check valid with no errors or warnings; 34 Battery Notes entries loaded; battery and appliance traces finished without relevant errors; active appliance onset timestamps unchanged across HA restart; managed backup completed successfully at 14:48 America/Chicago. Next scheduled backup: September 13 at 03:00.
