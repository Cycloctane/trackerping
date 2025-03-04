trackerping
===

Connectivity checker for Bittorrent trackers.

## Usage

### Ping a single tracker

Ping a single tracker url and print the result.

```bash
python3 trackerping.py http://tracker.example.com/announce
python3 trackerping.py --timeout=10 udp://tracker.example.com:80/announce
```

### Verify a trackerslist

Ping all trackers url in a local or remote trackerslist (one url per line).

```bash
python3 trackerping.py -l ./trackerslist.txt
python3 trackerping.py -l https://example.com/trackerslist.txt
```

Write available trackers to the new trackerslist:

```bash
python3 trackerping.py -l -o ./newtrackerslist.txt https://example.com/trackerslist.txt
```
