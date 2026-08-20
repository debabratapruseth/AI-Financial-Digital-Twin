"""SimPy payment-capacity, outage, failover, and backlog simulation."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

try:
    import simpy
except ImportError:  # pragma: no cover - surfaced with a helpful runtime error
    simpy = None


@dataclass(frozen=True)
class OperationalImpact:
    timeseries: pd.DataFrame
    peak_backlog_bn: float
    ending_backlog_bn: float
    payment_availability: float
    recovery_time_hours: float
    customers_affected: int
    applications_affected: int
    primary_recovery_time_hours: float
    backlog_clearance_time_hours: float
    backlog_cleared: bool


def application_failover_states(applications: pd.DataFrame, affected_applications: list[str],
                                failed_region: str, backup_region: str, simulation_hour: float,
                                outage_duration_hours: float, backup_activation_delay_hours: float,
                                region_backup_capacity_pct: float) -> pd.DataFrame:
    """Calculate application state from deployment data and scenario time only."""
    affected = set(affected_applications)
    records = []
    for row in applications.itertuples(index=False):
        is_affected = row.application in affected
        directly_hosted = is_affected and row.primary_region == failed_region
        has_backup = pd.notna(row.backup_region)
        has_designated_backup = has_backup and row.backup_region == backup_region
        failover_hours = 0.0 if pd.isna(row.failover_time_minutes) else float(row.failover_time_minutes) / 60.0
        ready_hour = max(float(backup_activation_delay_hours), failover_hours)
        if not is_affected:
            status, active_region, capacity = "Active", row.primary_region, float(row.normal_capacity_pct)
        elif simulation_hour >= outage_duration_hours:
            status = "Primary recovered" if directly_hosted else "Dependency restored"
            active_region, capacity = row.primary_region, float(row.normal_capacity_pct)
        elif not directly_hosted:
            if simulation_hour < backup_activation_delay_hours:
                status, active_region, capacity = "Dependency impacted", row.primary_region, 0.0
            else:
                status, active_region = "Recovered via dependency", row.primary_region
                capacity = min(float(row.normal_capacity_pct), float(region_backup_capacity_pct) * 100.0)
        elif not has_designated_backup:
            status, active_region, capacity = "No backup / unavailable", None, 0.0
        elif simulation_hour < ready_hour:
            status, active_region, capacity = "Waiting for failover", None, 0.0
        else:
            capacity = min(float(row.backup_capacity_pct), float(region_backup_capacity_pct) * 100.0)
            status = "Recovered" if capacity >= float(row.normal_capacity_pct) else "Recovered degraded"
            active_region = backup_region
        records.append({
            "application": row.application, "service": row.service,
            "primary_region": row.primary_region, "backup_region": row.backup_region,
            "backup_mode": row.backup_mode, "failover_time_minutes": row.failover_time_minutes,
            "normal_capacity_pct": float(row.normal_capacity_pct),
            "backup_capacity_pct": float(row.backup_capacity_pct), "criticality": row.criticality,
            "affected_by_failure": is_affected, "has_backup": has_backup,
            "directly_hosted_in_failed_region": directly_hosted,
            "has_designated_backup": has_designated_backup, "failover_ready_hour": ready_hour,
            "simulation_hour": float(simulation_hour), "application_status": status,
            "active_region": active_region, "effective_capacity_pct": capacity,
        })
    return pd.DataFrame(records)


def simulate_payments(duration_hours: int = 24, arrival_rate_bn_per_hour: float = 0.25,
                      normal_capacity_bn_per_hour: float = 0.32, outage_start_hour: float = 2.0,
                      recovery_time_hours: float = 4.0, impaired_capacity_fraction: float = 0.1,
                      backup_capacity_fraction: float = 0.7, backup_activation_hours: float = 2.0,
                      post_recovery_capacity_fraction: float = 1.0,
                      prioritisation_factor: float = 1.0, customers: int = 4_418_000,
                      outage_sensitivity: float = 0.8, applications_affected: int = 4,
                      seed: int = 42) -> OperationalImpact:
    if simpy is None:
        raise ImportError("simpy is required; install requirements.txt")
    env = simpy.Environment()
    records: list[dict[str, float | str | bool]] = []
    state = {"backlog": 0.0, "processed": 0.0, "arrived": 0.0, "available_hours": 0.0}
    rng = np.random.default_rng(seed)
    primary_recovery_hour = outage_start_hour + recovery_time_hours
    backup_activation_hour = outage_start_hour + backup_activation_hours
    backlog_clearance_hour: float | None = None

    def payment_process():
        for hour in range(duration_hours):
            arrivals = max(0.0, float(rng.normal(arrival_rate_bn_per_hour, arrival_rate_bn_per_hour * .08)))
            backlog_before = state["backlog"]
            if hour < outage_start_hour:
                capacity_fraction = 1.0
                operating_state = "normal"
            elif hour < backup_activation_hour:
                capacity_fraction = impaired_capacity_fraction
                operating_state = "primary_failed_backup_unavailable"
            elif hour < primary_recovery_hour:
                capacity_fraction = backup_capacity_fraction
                operating_state = "backup_degraded"
            elif state["backlog"] > 1e-12:
                capacity_fraction = post_recovery_capacity_fraction
                operating_state = "primary_recovered_backlog_clearance"
            else:
                capacity_fraction = 1.0
                operating_state = "normal"
            capacity = normal_capacity_bn_per_hour * capacity_fraction * prioritisation_factor
            available = state["backlog"] + arrivals
            processed = min(available, capacity)
            state["backlog"] = max(0.0, available - processed)
            state["processed"] += processed
            state["arrived"] += arrivals
            state["available_hours"] += min(1.0, capacity_fraction)
            customers_affected_at_hour = int(
                customers * min(1.0, max(0.0, 1.0 - min(1.0, capacity_fraction)) * outage_sensitivity * 3.0))
            event_labels = []
            if hour == outage_start_hour:
                event_labels.append("Primary region failed")
            if hour == backup_activation_hour:
                event_labels.append("Backup region activated")
            if hour == primary_recovery_hour:
                event_labels.append("Primary region recovered")
            nonlocal backlog_clearance_hour
            if (hour >= primary_recovery_hour and backlog_before > 1e-12
                    and state["backlog"] <= 1e-12 and backlog_clearance_hour is None):
                backlog_clearance_hour = float(hour + 1)
                event_labels.append("Backlog cleared")
            records.append({"hour": hour, "arrivals_bn": arrivals, "processed_bn": processed,
                            "capacity_bn": capacity, "backlog_bn": state["backlog"],
                            "capacity_fraction": capacity_fraction, "operating_state": operating_state,
                            "primary_available": not (outage_start_hour <= hour < primary_recovery_hour),
                            "backup_available": backup_activation_hour <= hour < primary_recovery_hour,
                            "customers_affected": customers_affected_at_hour,
                            "event": "; ".join(event_labels)})
            yield env.timeout(1)

    env.process(payment_process())
    env.run()
    frame = pd.DataFrame(records)
    availability = state["available_hours"] / duration_hours
    affected_fraction = min(1.0, (1.0 - availability) * outage_sensitivity * 3.0)
    cleared = backlog_clearance_hour is not None or float(frame["backlog_bn"].iloc[-1]) <= 1e-12
    total_recovery = (backlog_clearance_hour if backlog_clearance_hour is not None
                      else (primary_recovery_hour if float(frame["backlog_bn"].iloc[-1]) <= 1e-12 else float(duration_hours)))
    total_recovery = max(0.0, total_recovery - outage_start_hour)
    return OperationalImpact(frame, float(frame["backlog_bn"].max()), float(frame["backlog_bn"].iloc[-1]),
                             availability, total_recovery, int(customers * affected_fraction),
                             applications_affected if recovery_time_hours > 0 else 0,
                             recovery_time_hours, total_recovery, cleared)
