from __future__ import annotations

import unittest

from computer.now_playing import NowPlaying, parse_spotify, window_titles

PLAYING = (
    '"Spotify.exe","1234","Console","1","250.000 K","Running","PC\\\\Du","0:01:02","Daft Punk - Get Lucky"\n'
    '"Spotify.exe","1240","Console","1","90.000 K","Running","PC\\\\Du","0:00:01","N/A"\n'
)
PAUSED = '"Spotify.exe","1234","Console","1","250.000 K","Running","PC\\\\Du","0:01:02","Spotify Premium"\n'


class NowPlayingTests(unittest.TestCase):
    def test_playing(self) -> None:
        result = parse_spotify(window_titles(PLAYING), True)
        self.assertEqual(result, {"running": True, "playing": True, "track": "Get Lucky", "artist": "Daft Punk"})

    def test_paused_and_closed(self) -> None:
        self.assertEqual(parse_spotify(window_titles(PAUSED), True)["playing"], False)
        self.assertEqual(parse_spotify([], False)["running"], False)

    def test_song_with_dash_in_title(self) -> None:
        result = parse_spotify(["Artista - Música - Ao Vivo"], True)
        self.assertEqual((result["artist"], result["track"]), ("Artista", "Música - Ao Vivo"))

    def test_cache_and_errors(self) -> None:
        calls: list[int] = []

        def reader():
            calls.append(1)
            return PLAYING, True

        player = NowPlaying(reader, cache_seconds=60)
        player.get()
        player.get()
        self.assertEqual(len(calls), 1)
        player.invalidate()
        player.get()
        self.assertEqual(len(calls), 2)

        def broken():
            raise OSError("sem tasklist")

        self.assertIn("error", NowPlaying(broken).get())


if __name__ == "__main__":
    unittest.main()
