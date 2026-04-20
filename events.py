"""
events.py -- Event names and constructors for the JSON protocol.

Event names:  events.PING, events.ECHO, etc. (for listeners)
Constructors: events.ping(msg), events.echo(data, t), etc. (for senders)
"""

try:
    from . import protocol
except ImportError:
    import protocol


# -- Event name constants (use these in if/elif listeners) -----------------
WELCOME = "welcome"



# -- Server -> Client constructors ----------------------------------------

def welcome(client_id: str, server_id: str) -> str:
    """Server greets a newly connected client with their assigned ID."""
    return protocol.encode(WELCOME, {
        "id": client_id,
        "server_id": server_id,
    })

ECHO    = "echo"

def echo(original_data: dict, server_time: str) -> str:
    """Server echoes back a client's ping."""
    return protocol.encode(ECHO, {
        "original": original_data,
        "server_time": server_time,
    })

TIME    = "time"

def time_broadcast(server_time: str) -> str:
    """Server broadcasts the current time to all clients."""
    return protocol.encode(TIME, {"server_time": server_time})

ERROR   = "error"

def error(reason: str) -> str:
    """Server reports an error to a client."""
    return protocol.encode(ERROR, {"reason": reason})


# -- Client -> Server constructors ----------------------------------------
PING    = "ping"

def ping(message: str) -> str:
    """Client sends a ping with a text message."""
    return protocol.encode(PING, {"message": message})

CLIENT_INFO = "client_info"

def client_info(computer_name: str) -> str:
    """Client sends identifying machine metadata to the server."""
    return protocol.encode(CLIENT_INFO, {"computer_name": computer_name})

EXAM_POLICY = "exam_policy"

def exam_policy(policy: dict) -> str:
    """Server sends the current client-enforced exam policy."""
    return protocol.encode(EXAM_POLICY, policy)

POLICY_UPDATE = "policy_update"

def policy_update(policy: dict) -> str:
    """Server pushes an updated client-enforced exam policy."""
    return protocol.encode(POLICY_UPDATE, policy)

POLICY_APPLIED = "policy_applied"

def policy_applied(policy_version: str, *, ok: bool = True, reason: str = "") -> str:
    """Client acknowledges that a policy version was applied or rejected."""
    payload = {
        "policy_version": policy_version,
        "ok": bool(ok),
    }
    if reason:
        payload["reason"] = reason
    return protocol.encode(POLICY_APPLIED, payload)

SAVESCREEN = "savescreen"

def savescreen() -> str:
    """Server requests the client to save the screen."""
    return protocol.encode(SAVESCREEN, {})

# -- Exam Flow Events ----------------------------------------------------

START_EXAM = "start_exam"

def start_exam() -> str:
    """Client asserts they are ready to begin the countdown."""
    return protocol.encode(START_EXAM, {})

SYNC_TIME = "sync_time"

def sync_time(
    remaining_seconds: int,
    *,
    timer_state: str = "running",
    pause_source: str = "",
    reason: str = "",
) -> str:
    """Server tells client the exact remaining seconds."""
    payload = {
        "remaining_seconds": remaining_seconds,
        "timer_state": timer_state,
    }
    if pause_source:
        payload["pause_source"] = pause_source
    if reason:
        payload["reason"] = reason
    return protocol.encode(SYNC_TIME, payload)

SESSION_STATE = "session_state"

def session_state(
    state: str,
    remaining_seconds: int,
    *,
    reason: str = "",
    resume_allowed: bool = False,
    policy_version: str = "",
    pause_source: str = "",
) -> str:
    """Server sends the authoritative session state for connect/reconnect flow."""
    payload = {
        "state": state,
        "remaining_seconds": int(remaining_seconds),
        "resume_allowed": bool(resume_allowed),
    }
    if reason:
        payload["reason"] = reason
    if policy_version:
        payload["policy_version"] = policy_version
    if pause_source:
        payload["pause_source"] = pause_source
    return protocol.encode(SESSION_STATE, payload)

PAUSE_EXAM = "pause_exam"

def pause_exam(remaining_seconds: int, *, source: str = "admin", reason: str = "") -> str:
    """Server pauses a client's exam timer while monitoring continues."""
    payload = {
        "remaining_seconds": remaining_seconds,
        "source": source,
    }
    if reason:
        payload["reason"] = reason
    return protocol.encode(PAUSE_EXAM, payload)

RESUME_EXAM = "resume_exam"

def resume_exam(remaining_seconds: int, *, source: str = "admin", reason: str = "") -> str:
    """Server resumes a previously paused exam timer."""
    payload = {
        "remaining_seconds": remaining_seconds,
        "source": source,
    }
    if reason:
        payload["reason"] = reason
    return protocol.encode(RESUME_EXAM, payload)

EXAM_END = "exam_end"

def exam_end() -> str:
    """Server tells client their exam duration has depleted."""
    return protocol.encode(EXAM_END, {})

GET_PROCESSES = "get_processes"

def get_processes() -> str:
    """Server requests an immediate full process report from the client."""
    return protocol.encode(GET_PROCESSES, {})

PROCESS_BLACKLIST = "process_blacklist"

def process_blacklist(entries: list[str], version: str) -> str:
    """Server sends the current process blacklist to a client."""
    return protocol.encode(
        PROCESS_BLACKLIST,
        {
            "entries": entries,
            "version": version,
        },
    )

PROCESS_CATCH = "process_catch"

def process_catch(matches: list[dict], blacklist_version: str) -> str:
    """Client reports a detected blacklisted process."""
    return protocol.encode(
        PROCESS_CATCH,
        {
            "matches": matches,
            "blacklist_version": blacklist_version,
        },
    )

INCIDENT_REPORT = "incident_report"

def incident_report(payload: dict) -> str:
    """Client reports an incident lifecycle event and any related metadata."""
    return protocol.encode(INCIDENT_REPORT, payload)

INCIDENT_RECEIVED = "incident_received"

def incident_received(
    incident_id: str,
    *,
    stored: bool = True,
    artifact_path: str = "",
    reason: str = "",
) -> str:
    """Server acknowledges an incident report."""
    payload = {
        "incident_id": incident_id,
        "stored": bool(stored),
    }
    if artifact_path:
        payload["artifact_path"] = artifact_path
    if reason:
        payload["reason"] = reason
    return protocol.encode(INCIDENT_RECEIVED, payload)

KILL_PROCESS = "kill_process"

def kill_process(
    pid: int,
    *,
    incident_id: str = "",
    process_name: str = "",
    reason: str = "",
) -> str:
    """Server requests a client to terminate a specific process ID."""
    payload = {"pid": int(pid)}
    if incident_id:
        payload["incident_id"] = incident_id
    if process_name:
        payload["process_name"] = process_name
    if reason:
        payload["reason"] = reason
    return protocol.encode(KILL_PROCESS, payload)

KILL_PROCESS_RESULT = "kill_process_result"

def kill_process_result(
    pid: int,
    *,
    incident_id: str = "",
    ok: bool = False,
    process_name: str = "",
    message: str = "",
) -> str:
    """Client reports the outcome of a kill-process command."""
    payload = {
        "pid": int(pid),
        "ok": bool(ok),
    }
    if incident_id:
        payload["incident_id"] = incident_id
    if process_name:
        payload["process_name"] = process_name
    if message:
        payload["message"] = message
    return protocol.encode(KILL_PROCESS_RESULT, payload)

FINISH_EXAM = "finish_exam"

def finish_exam(reason: str = "") -> str:
    """Server requests the client to finish the exam and submit work."""
    return protocol.encode(FINISH_EXAM, {"reason": reason})
