# Video Extensão Download

Baixa um vídeo pelo ícone da extensão. Cole o link, a rede aparece na hora, você escolhe a qualidade, o nome já vem com a rede, a data e a hora, e o arquivo pode sair em ZIP.

A ideia vem do [media-downloader](https://github.com/mateusands/media-downloader), um programa de mesa que baixa com yt-dlp. Aqui o uso é a extensão. O download roda num serviço local na máquina de quem está usando, porque o navegador não executa o yt-dlp.

## Instalar

1. Baixe o ZIP da release.
2. Extraia a pasta `video-extensao-download`.
3. Dê dois cliques em **Instalar**. No Linux o arquivo é `Instalar.desktop`. No Windows é `Instalar.bat`.
4. Carregue a extensão:
   - Brave ou Chrome: abra `brave://extensions` ou `chrome://extensions`, ative o modo do desenvolvedor, escolha "Carregar sem compactação" e aponte para a pasta `extension`
   - Firefox: abra `about:debugging`, escolha "Este Firefox" e carregue `extension/manifest.json`

Na primeira vez o sistema pode pedir para confiar no arquivo e, se ainda faltarem, para instalar Python, FFmpeg e Node. O programa não fica aberto: a extensão inicia o serviço ao colar um link, ao usar **Aba** ou o menu do botão direito, e ele se encerra sozinho depois do download. Isso vale no Linux e no Windows. Fechar e abrir a extensão deixa o campo vazio, sem o link anterior e sem o vídeo que já foi baixado. Se uma instalação antiga abria o programa junto com o Windows, rode **Instalar** de novo para tirar esse atalho. Se a extensão já estava carregada, recarregue ela depois do Instalar. Os vídeos caem em `~/Downloads/Video Extensao Download` no Linux e em `Downloads\Video Extensao Download` no Windows.

Um segundo clique em **Instalar** atualiza o yt-dlp.

## Redes

A extensão reconhece YouTube, Instagram, TikTok, X, Facebook, Vimeo, Dailymotion, SoundCloud, Twitch, Reddit, Pinterest, LinkedIn, Threads, Kwai, Bilibili e Snapchat. Outro link `http` ou `https` entra como **Outra rede** e o yt-dlp tenta baixar. A barra para escolher um trecho existe só no YouTube.

## O que dá para fazer

- Colar qualquer link `http` ou `https`, usar o botão **Aba** ou o menu do botão direito
- Ver a rede reconhecida na hora
- Escolher a qualidade: melhor, 1080p, 720p, 480p, 360p ou só áudio
- No YouTube, marcar o trecho numa barra ou digitar o início e o fim. Vazio baixa o vídeo inteiro
- Receber o nome pronto, por exemplo `youtube_2026-10-30_21-05-09`, e editar se quiser
- Marcar formato compactado para receber um ZIP
- Acompanhar o progresso, cancelar e ler o resultado em verde ou vermelho
- Abrir a pasta do vídeo no gerenciador de arquivos

Um link por vez. Verde indica serviço no ar ou download concluído. Vermelho indica serviço desligado, link inválido ou falha.

## Uso

1. Clique no ícone da extensão
2. Cole o link, ou use **Aba**. O selo vai para **iniciando** e, em seguida, para **no ar**
3. Escolha a qualidade
4. No YouTube, arraste a barra ou digite o início e o fim, por exemplo `1:30` ou `90,5`. Deixe vazio para baixar o vídeo inteiro. O tempo digitado é o corte e demora mais, porque o trecho é recodificado
5. Ajuste o nome se quiser
6. Marque **Formato compactado (ZIP)** quando quiser o arquivo em ZIP
7. Clique em **Baixar**
8. Clique em **Abrir pasta** para ver o arquivo no gerenciador

Depois do download o serviço se encerra sozinho. Feche e abra a extensão para começar de novo, com o campo vazio, e cole outro link. Se o selo ficar **offline**, abra **Instalar** de novo.

## Desenvolvimento

Python 3.10 ou mais novo, FFmpeg e Node, Deno ou Bun. A porta padrão é `8734`. `MDE_PORT` muda a porta. `MDE_DOWNLOADS` muda a pasta de destino. O mesmo número de porta precisa estar em `extension/popup.js`, na constante `SERVICE`.

```bash
./run.sh
python3 -m unittest discover -s tests -v
node tests/detect.test.js
python3 scripts/package_extension.py
```

`./run.sh` sobe o serviço neste terminal e fica nele até o processo encerrar. No Linux do dia a dia o soquete escuta a porta e só inicia o programa quando a extensão cola um link, usa **Aba** ou o menu do botão direito. No Windows o **Instalar** registra o mesmo início no navegador e tira o atalho da inicialização. O programa se encerra sozinho depois do download. Enquanto ele está no ar, a mesma tela também responde em `http://127.0.0.1:8734/`. O **Instalar** não abre essa página. Os testes não baixam nada da internet. O ZIP de instalação fica em `dist/video-extensao-download.zip`.

## Aviso

Uso pessoal. Respeite os termos de cada site e os direitos do vídeo.

## Licença

MIT. yt-dlp e FFmpeg seguem as licenças dos próprios projetos.
