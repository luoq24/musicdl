from musicdl import musicdl

music_client = musicdl.MusicClient(
    music_sources=['MiguMusicClient', 'NeteaseMusicClient', 'QQMusicClient', 'KuwoMusicClient', 'QianqianMusicClient']
)
music_client.startcmdui()