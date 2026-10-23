# assets/musica/

Aqui van las pistas instrumentales de fondo (.mp3, .wav u .ogg). El motor
(`productor_mxl.py`) elige una al azar en cada video, la pone en loop hasta
cubrir la duracion total, la mezcla a bajo volumen (`MUSIC_VOLUME = 0.12`,
para no tapar la voz) y le aplica fade in/out automatico. Es opcional: si
esta carpeta esta vacia, el video se genera igual, solo con la voz.

## Que subir aqui

- Musica INSTRUMENTAL (sin voces) para no chocar con la narracion.
- Tono alegre/infantil, acorde al canal "mxl Aprende".
- Duracion minima recomendada: ~20-30s (se hace loop automatico si el
  video dura mas que la pista).
- Formatos aceptados: `.mp3`, `.wav`, `.ogg`.

## De donde sacar pistas con licencia segura para YouTube

Para poder monetizar/publicar sin reclamos de copyright, usa musica libre
de regalias con licencia explicita para uso comercial/YouTube, por ejemplo:

- YouTube Audio Library (Estudio de creador de YouTube > Audio Library)
- Pixabay Music (pixabay.com/music) — licencia libre de regalias
- Free Music Archive (freemusicarchive.org), filtrando por licencia CC
  que permita uso comercial

Guarda el nombre del archivo simple y descriptivo, ej. `fondo_alegre_01.mp3`.
No hace falta editarlas ni recortarlas: el script se encarga de loopear,
bajar el volumen y aplicar los fades.
