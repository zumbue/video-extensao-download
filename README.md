# Video Extensão Download

Baixa um vídeo a partir de um link. A página reconhece a rede, deixa escolher a qualidade, preenche o nome com a rede, a data e a hora, e pode entregar o arquivo em ZIP.

A ideia vem do [media-downloader](https://github.com/mateusands/media-downloader), um programa de mesa que baixa com yt-dlp. Aqui a interface abre no navegador. O download roda num serviço local na máquina de quem está usando, porque o navegador não executa o yt-dlp.

## Instalar

1. Baixe o ZIP da release.
2. Extraia a pasta `video-extensao-download`.
3. Dê dois cliques em **Instalar**. No Linux o arquivo é `Instalar.desktop`. No Windows é `Instalar.bat`.

A página `http://127.0.0.1:8734/` abre sozinha. Cole o link e clique em **Baixar**.

Na primeira vez o sistema pode pedir para confiar no arquivo e, se ainda faltarem, para instalar Python, FFmpeg e Node. No Linux o programa não fica aberto o tempo todo: a extensão inicia o serviço ao colar um link e ele se encerra sozinho depois do download. Os vídeos caem em `~/Downloads/Video Extensao Download` no Linux e em `Downloads\Video Extensao Download` no Windows.

Um segundo clique em **Instalar** atualiza o yt-dlp e abre a página de novo.

## O que dá para fazer

- Colar qualquer link `http` ou `https`
- Ver a rede reconhecida na hora (YouTube, Instagram, TikTok, X e outras)
- Escolher a qualidade: melhor, 1080p, 720p, 480p, 360p ou só áudio
- No YouTube, marcar o trecho numa barra ou digitar o início e o fim. Vazio baixa o vídeo inteiro
- Receber o nome pronto, por exemplo `youtube_2026-10-30_21-05-09`, e editar se quiser
- Marcar formato compactado para receber um ZIP
- Acompanhar o progresso, cancelar e ler o resultado em verde ou vermelho
- Abrir a pasta do vídeo no gerenciador de arquivos

Um link por vez. Verde indica serviço no ar ou download concluído. Vermelho indica serviço desligado, link inválido ou falha.

## Extensão, se quiser o ícone na barra

A página local já baixa. A extensão é opcional e faz o mesmo, com a aba aberta e o menu do botão direito.

1. Abra `brave://extensions` ou `chrome://extensions`
2. Ative o modo do desenvolvedor
3. Escolha "Carregar sem compactação" e aponte para a pasta `extension`

No Firefox, abra `about:debugging`, escolha "Este Firefox" e carregue `extension/manifest.json`.

## Uso

1. Cole o link. O selo vai para **iniciando** e, em seguida, para **no ar**
2. Escolha a qualidade
3. No YouTube, arraste a barra ou digite o início e o fim, por exemplo `1:30` ou `90,5`. Deixe vazio para baixar o vídeo inteiro. O tempo digitado é o corte e demora mais, porque o trecho é recodificado
4. Ajuste o nome se quiser
5. Marque **Formato compactado (ZIP)** quando quiser o arquivo em ZIP
6. Clique em **Baixar**
7. Clique em **Abrir pasta** para ver o arquivo no gerenciador

Depois do download o serviço se encerra sozinho. Cole outro link para baixar de novo. Se o selo ficar **offline**, abra **Instalar** de novo.

## Desenvolvimento

Python 3.10 ou mais novo, FFmpeg e Node, Deno ou Bun. A porta padrão é `8734`. `MDE_PORT` muda a porta. `MDE_DOWNLOADS` muda a pasta de destino. O mesmo número de porta precisa estar em `extension/popup.js`, na constante `SERVICE`.

```bash
./run.sh
python3 -m unittest discover -s tests -v
node tests/detect.test.js
python3 scripts/package_extension.py
```

`./run.sh` sobe o serviço neste terminal e fica nele até o processo encerrar. No Linux do dia a dia o soquete escuta a porta e só inicia o programa quando a extensão cola um link. O programa se encerra sozinho depois do download. Os testes não baixam nada da internet. O ZIP de instalação fica em `dist/video-extensao-download.zip`.

## Aviso

Uso pessoal. Respeite os termos de cada site e os direitos do vídeo.

## Licença

MIT. yt-dlp e FFmpeg seguem as licenças dos próprios projetos.
