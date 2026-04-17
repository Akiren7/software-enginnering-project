"""
TEMPLATE: How to add a new event to the server-client protocol.

Replace every instance of YOUR_EVENT with your actual event name,
then follow the 3 steps marked with [STEP 1], [STEP 2], [STEP 3].
"""


# ==========================================================================
# [STEP 1] common/events.py -- Add a constant + constructor(s)
# ==========================================================================

# At the top with the other constants:
YOUR_EVENT = "your_event"

# Constructor for sending FROM CLIENT -> SERVER:
def your_event_request(some_param: str) -> str:
    """Client sends a your_event request."""
    return protocol.encode(YOUR_EVENT, {"some_param": some_param})

# Constructor for sending FROM SERVER -> CLIENT:
def your_event_response(result: str) -> str:
    """Server replies to a your_event request."""
    return protocol.encode(YOUR_EVENT, {"result": result})

# NOTE: You don't always need both. If only the server sends it (like time
# broadcasts), you only need one constructor. Same if only the client sends it.


# ==========================================================================
# [STEP 2] server/handlers.py -- Handle the event in the WebSocket handler
# ==========================================================================

# In websocket_handler(), add an elif inside the message loop:

#   if event == events.PING:
#       ...
#   elif event == events.YOUR_EVENT:              # <-- ADD THIS BLOCK
#       # Do your server-side logic here
#       result = "some result"
#       await ws.send_str(events.your_event_response(result))
#   else:
#       await ws.send_str(events.error(...))


# ==========================================================================
# [STEP 3] client/ws_client.py -- Handle the server's reply in the listener
# ==========================================================================

# In listener(), add an elif for displaying the response:

#   if event == events.WELCOME:
#       ...
#   elif event == events.YOUR_EVENT:              # <-- ADD THIS BLOCK
#       print(f"[WS] Your event result: {data['result']}")
#   else:
#       print(f"[WS] {event}: {data}")


# ==========================================================================
# OPTIONAL: Trigger it from the client
# ==========================================================================

# In sender() or main(), send the request:
#   await ws.send_str(events.your_event_request("hello"))
#
# Or add a special keyword the user can type:
#   if text == "/status":
#       await ws.send_str(events.your_event_request("check"))
#   else:
#       await ws.send_str(events.ping(text))
