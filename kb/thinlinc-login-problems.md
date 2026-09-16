# ThinLinc will not connect

What a particular ThinLinc connection failure usually means, and what to try for
it. The remedies themselves are in the User Guide's ThinLinc troubleshooting
page; this page is the map from the symptom a user sees to the cause behind it,
because the error a user can report is rarely the word its remedy is filed
under.

Most ThinLinc trouble is one of three things: a home directory over quota, a
stale session left behind on a login node, or conda in `~/.bashrc`. Try those
three first, in that order, whatever the symptom.

## Login fails, or logs you straight back out

ThinLinc accepts the CNetID, password and Duo approval and then drops the
session, or fails with an error instead of opening a desktop. Two usual causes:

- **The home directory is over quota.** ThinLinc writes cache files into the
  home directory at login and cannot start a session when there is no room for
  them. Log in over SSH and run `quota`; an `expired` flag on either the blocks
  or the files row of the relevant home directory is the cause, and the number
  of files matters as much as the space used.
- **A conda initialisation block in `~/.bashrc`.** The lines `conda init` adds
  break the login shell ThinLinc starts, and removing them fixes the session.

## "Server disconnected" after logging in

A stale browser cache, or a previous ThinLinc session that was never closed
properly and is still held on a login node. Clear the browser cache, and clear
the old session on **every** login node of the cluster rather than only the one
being connected to now - a session left on `login1` will break a connection made
to `login2`.

Sessions dropping repeatedly, rather than once, has a second cause with nothing
to do with the account: ThinLinc's `vsmagent` service stopped on one login node
of the cluster. That is the same node-level fault as the internal error below,
and it is diagnosed the same way.

## The desktop opens but the display is wrong

Leftover GNOME and session state in the home directory. Removing the cached
desktop configuration from `~/.cache`, `~/.config`, `~/.dbus` and
`~/.local/share` and logging in again rebuilds it.

## "No agent available"

The ThinLinc service itself, not the account: there is no session agent to hand
the connection to. Nothing a user can do from their side fixes this, so report it
to the help desk with the cluster name and the time of the attempt.

## "Cannot allocate license"

Every ThinLinc licence is in use, so there is none left to give this connection.
A capacity limit rather than a fault; a later attempt normally succeeds.

## Keeping a session that works

Two habits that avoid most of the above:

- **Connect to the cluster's own address, not to a numbered login node** - use
  `midway3.rcc.uchicago.edu` rather than `midway3-login1.rcc.uchicago.edu`, and
  let it place the session.
- **Do not log out of the desktop when you are finished; close the browser
  window or the client instead.** Closing leaves the session running and
  reconnects you to the same desktop next time, while logging out and back in is
  what leaves stale sessions behind.

## "Internal error. If this problem persists, please contact your system administrator."

Shown after the CNetID, the password and the Duo approval have all been
accepted. This one is usually **the login node and not the account**: the
ThinLinc service on a single login node has failed - a `dbus` fault, or its
`vsmagent` service stopped - while every other node of the same cluster is
serving sessions normally. It has happened on `midway3-login4` and, separately,
on `midway3-login3`, in both cases for a user who could log in perfectly well
through one of the cluster's other login nodes.

So the thing that identifies it is to **connect to a numbered login node
explicitly, and to more than one**: `midway3-login1.rcc.uchicago.edu`,
`-login2`, `-login3` and so on, instead of the load-balanced
`midway3.rcc.uchicago.edu` that picks for you. If one of them opens a desktop
and another gives the internal error, the error belongs to that node, there is
nothing wrong with the account, and reporting *which node* is the useful thing
to report - it is what gets it fixed, and nothing a user can do from their side
will fix it. If all of them give the same error, the three first-line remedies
at the top are the likelier cause after all.

Note that this is the one symptom for which connecting to a numbered node is
the right move, and it is the opposite of the standing advice above. That advice
avoids *creating* problems; this diagnoses one that already exists.

## Errors not listed here

For an error whose text is not above, the three first-line remedies at the top
are still worth trying, and so is trying the browser and the client separately,
because the two failing differently narrows the problem. Beyond that it is a
help desk ticket, and the useful things to include are the cluster, the login
node if you connected to one by name, whether it was the browser or the client,
the exact time of each attempt, and the operating system and client version.
