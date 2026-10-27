"""Route bare numeric replies to the latest song/cover workflow for the same user and conversation."""
import time
ACTIVE={}
def claim(key,workflow):
    ACTIVE[tuple(key)]=(workflow,time.time()+1800)
def active(key,workflow):
    value=ACTIVE.get(tuple(key))
    return bool(value and value[0]==workflow and value[1]>time.time())
def clear(key,workflow):
    if active(key,workflow):ACTIVE.pop(tuple(key),None)
