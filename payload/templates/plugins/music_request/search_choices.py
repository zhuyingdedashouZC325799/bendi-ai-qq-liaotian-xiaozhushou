"""Discovery may be fuzzy; downloading always uses the user's selected track."""
import re,unicodedata

def compact(value):
    return re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',str(value)).casefold())

def candidate_match(query,song):
    wanted=compact(query)
    title=compact(song.get('name',''))
    artists=[compact(a.get('name','')) for a in song.get('artists',[])]
    return bool(wanted and title and (wanted in title or wanted in ''.join(artists)
        or wanted in {''.join(artists)+title,title+''.join(artists)}))

def rank_choices(query,songs):
    wanted=compact(query)
    def rank(song):
        title=compact(song.get('_catalog_name') or song['name']);artist=compact(song['artist'])
        exact=wanted in {title,artist+title,title+artist}
        return (not exact,not(wanted in title),song.get('provider')!='local')
    choices=[];seen=set()
    for song in sorted(songs,key=rank):
        identity=(compact(song['name']),compact(song['artist']),compact(song.get('album','')))
        if identity in seen:continue
        seen.add(identity);choices.append(song)
        if len(choices)==8:break
    return choices
