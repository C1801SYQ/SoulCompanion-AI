"""Read-only, fail-closed target verification for independently approved PC03 writes.

Legacy preflight reports its configured region. PC03 must additionally verify
the region and database returned by DescribeEnvInfo, rather than trusting that
configured value as evidence of the actual environment.
"""

from __future__ import annotations

from collections.abc import Callable

from cloud_admin import AdminError, ENV_ID, REGION


DATABASE_ID = "tnt-28wj48qn2"
TargetReader = Callable[[], dict]


def verify_target(
    preflight: TargetReader, environment_info: TargetReader, *, error: str,
) -> dict:
    """Validate billing and independently read actual environment identity.

Both callbacks are read-only. Callers must enforce their explicit authorization
gate before this helper, then perform no writes unless it returns successfully.
"""
    audit = preflight()
    if (
        not isinstance(audit, dict)
        or audit.get("env_id") != ENV_ID or audit.get("region") != REGION
        or audit.get("database_id") != DATABASE_ID
        or audit.get("package_id") != "baas_trial"
        or audit.get("overrun") is not False or audit.get("auto_renew") is not False
    ):
        raise AdminError(error)
    response = environment_info()
    environment = response.get("EnvInfo") if isinstance(response, dict) else None
    base = environment.get("EnvBaseInfo") if isinstance(environment, dict) else None
    if not isinstance(base, dict):
        raise AdminError(error)
    databases = base.get("Databases")
    if (
        base.get("EnvId") != ENV_ID or base.get("Region") != REGION
        or base.get("Status") != "NORMAL" or not isinstance(databases, list)
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("InstanceId"), str) or not item["InstanceId"]
            or not isinstance(item.get("Status"), str) or not item["Status"]
            for item in databases
        )
    ):
        raise AdminError(error)
    running = [item for item in databases if item["Status"] == "RUNNING"]
    if len(running) != 1 or running[0]["InstanceId"] != DATABASE_ID:
        raise AdminError(error)
    return audit
