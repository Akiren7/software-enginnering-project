"""
events.py -- Event names and constructors for the JSON protocol.

Event names:  events.PING, events.ECHO, etc. (for listeners)
Constructors: events.ping(msg), events.echo(data, t), etc. (for senders)
"""

import shared


# -- Event name constants (use these in if/elif listeners) -----------------
WELCOME = "welcome"



# -- Server -> Client constructors ----------------------------------------

def welcome(client_id: str, server_id: str) -> str:
    """Server greets a newly connected client with their assigned ID."""
    return shared.encode(WELCOME, {
        "id": client_id,
        "server_id": server_id,
    })

ECHO    = "echo"

def echo(original_data: dict, server_time: str) -> str:
    """Server echoes back a client's ping."""
    return shared.encode(ECHO, {
        "original": original_data,
        "server_time": server_time,
    })

TIME    = "time"

def time_broadcast(server_time: str) -> str:
    """Server broadcasts the current time to all clients."""
    return shared.encode(TIME, {"server_time": server_time})

ERROR   = "error"

def error(reason: str) -> str:
    """Server reports an error to a client."""
    return shared.encode(ERROR, {"reason": reason})


# -- Client -> Server constructors ----------------------------------------
PING    = "ping"

def ping(message: str) -> str:
    """Client sends a ping with a text message."""
    return shared.encode(PING, {"message": message})

SAVESCREEN = "savescreen"

def savescreen() -> str:
    """Server requests the client to save the screen."""
    return shared.encode(SAVESCREEN, {})

# -- Exam Flow Events ----------------------------------------------------

START_EXAM = "start_exam"

def start_exam() -> str:
    """Client asserts they are ready to begin the countdown."""
    return shared.encode(START_EXAM, {})

SYNC_TIME = "sync_time"

def sync_time(remaining_seconds: int) -> str:
    """Server tells client the exact remaining seconds."""
    return shared.encode(SYNC_TIME, {"remaining_seconds": remaining_seconds})

EXAM_END = "exam_end"

def exam_end() -> str:
    """Server tells client their exam duration has depleted."""
    return shared.encode(EXAM_END, {})

GET_PROCESSES = "get_processes"

def get_processes() -> str:
    """Server requests an immediate full process report from the client."""
    return shared.encode(GET_PROCESSES, {})

