"""
events.py -- Event names and constructors for the JSON protocol.

Event names:  events.PING, events.ECHO, etc. (for listeners)
Constructors: events.ping(msg), events.echo(data, t), etc. (for senders)
"""

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

def sync_time(remaining_seconds: int) -> str:
    """Server tells client the exact remaining seconds."""
    return protocol.encode(SYNC_TIME, {"remaining_seconds": remaining_seconds})

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

FINISH_EXAM = "finish_exam"

def finish_exam(reason: str = "") -> str:
    """Server requests the client to finish the exam and submit work."""
    return protocol.encode(FINISH_EXAM, {"reason": reason})
