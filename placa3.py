#!/usr/bin/env python3
import asyncio
from camadafisica import ZyboSerialDriver
from tcp import Servidor        # copie o arquivo do T2
from ip import IP               # copie o arquivo do T3
from slip import CamadaEnlace   # copie o arquivo do T4

## Implementação da camada de aplicação

# Este é um exemplo de um programa que faz eco, ou seja, envia de volta para
# o cliente tudo que for recebido em uma conexão.

import re

nicks = dict()
canais = dict()
resíduos = dict()

def responder_PING(conexao, dados):
    return conexao.enviar(b':server PONG server :' + dados + b'\r\n')

def validar_nick(conexao, nick_novo):
    nick_atual = nicks.get(conexao, b'temp')

    if not validar_nome(nick_novo):
        conexao.enviar(b':server 432 ' + nick_atual + b' ' + nick_novo + b' :Erroneous nickname\r\n')
        return

    if any(nick_novo.lower() == nome.lower() for nome in nicks.values()):
        conexao.enviar(b':server 433 ' + nick_atual + b' ' + nick_novo + b' :Nickname is already in use\r\n')
        return

    if nick_atual != b'*':
        conexao.enviar(b':' + nick_atual + b' NICK ' + nick_novo + b'\r\n')
        nicks[conexao] = nick_novo
        return

    nicks[conexao] = nick_novo
    conexao.enviar(b':server 001 ' + nick_novo + b' :Welcome\r\n')
    conexao.enviar(b':server 422 ' + nick_novo + b' :MOTD File is missing\r\n')

def sair_canal(conexao, dados):
    nome_canal = dados[0].split(b' ', 1)[0]

    canal_real = None
    for canal in canais:
        if canal.lower() == nome_canal.lower():
            canal_real = canal
            break

    if not canal_real or conexao not in canais[canal_real]:
        return

    part_msg = b':' + nicks[conexao] + b' PART ' + canal_real + b'\r\n'
    for membro in canais[canal_real][:]:
        membro.enviar(part_msg)

    canais[canal_real].remove(conexao)

def entrar_canal(conexao, parametros):
    nome_canal = parametros[0].strip()
    nome_canal_minusculo = nome_canal.lower()
    apelido_usuario = nicks[conexao]

    if nome_canal.startswith(b'#') and not validar_nome(nome_canal[1:]):
        conexao.enviar(b':server 403 canal :No such channel\r\n')
        return

    canal_existente = next(
        (canal for canal in canais if canal.lower() == nome_canal_minusculo),
        None
    )

    if canal_existente is None:
        canais[nome_canal] = [conexao]
        canal_existente = nome_canal
    else:
        canais[canal_existente].append(conexao)
        canais[canal_existente].sort(key=lambda c: nicks[c].lower())

    mensagem_join = b':' + apelido_usuario + b' JOIN :' + nome_canal + b'\r\n'
    for usuario in canais[canal_existente]:
        usuario.enviar(mensagem_join)

    apelidos_no_canal = [nicks[usuario] for usuario in canais[canal_existente]]
    resposta_usuarios = (
        b':server 353 ' + apelido_usuario + b' = ' + nome_canal + b' :'
    )

    for apelido in apelidos_no_canal:
        if len(resposta_usuarios) + len(apelido) < 510:
            resposta_usuarios += apelido + b' '
        else:
            conexao.enviar(resposta_usuarios.strip() + b'\r\n')
            resposta_usuarios = apelido + b' '

    conexao.enviar(resposta_usuarios.strip() + b'\r\n')
    conexao.enviar(
        b':server 366 ' + apelido_usuario + b' ' + nome_canal + b' :End of /NAMES list.\r\n'
    )

def enviar_mensagem(conexao, dados):
    quem_recebeu, _, mensagem = dados.partition(b' :')
    quem_mandou = nicks[conexao]

    if quem_recebeu.startswith(b'#'):
        for nome_canal in canais:
            if nome_canal.lower() == quem_recebeu.lower():
                for conexao_receptor in canais[nome_canal]:
                    if conexao_receptor != conexao:
                        conexao_receptor.enviar(
                            b':' + quem_mandou + b' PRIVMSG ' + quem_recebeu + b' :' + mensagem + b'\r\n'
                        )
                break
    else:
        for conexao_receptor, nick in nicks.items():
            if nick.lower() == quem_recebeu.lower():
                conexao_receptor.enviar(
                    b':' + quem_mandou + b' PRIVMSG ' + quem_recebeu + b' :' + mensagem + b'\r\n'
                )
                break

def sair(conexao):
    print(conexao, 'conexão fechada')

    msg_quit = b':' + nicks[conexao] + b' QUIT \r\n'

    canais_participando = [canal for canal, membros in canais.items() if conexao in membros]

    for canal in canais_participando:
        membros = canais[canal][:]
        for membro in membros:
            if membro == conexao:
                canais[canal].remove(conexao)
            else:
                membro.enviar(msg_quit)

        if not canais[canal]:
            del canais[canal]

    nicks.pop(conexao, None)
    resíduos.pop(conexao, None)
    conexao.fechar()

def validar_comando(conexao, msg):
    comando = msg[0].upper()
    dados = msg[1:]

    if comando == b'PING':
        responder_PING(conexao, dados[0] if dados else b'')

    elif comando == b'NICK' and dados:
        validar_nick(conexao, dados[0])

    elif comando == b'PRIVMSG' and len(dados) >= 2:
        enviar_mensagem(conexao, b' '.join(dados))

    elif comando == b'JOIN' and dados:
        entrar_canal(conexao, dados)

    elif comando == b'PART' and dados:
        sair_canal(conexao, dados)

def dados_recebidos(conexao, dados):
    if dados == b'':
        return sair(conexao)

    if conexao not in resíduos:
        resíduos[conexao] = b''

    resíduos[conexao] += dados

    while b'\n' in resíduos[conexao]:
        linha, restante = resíduos[conexao].split(b'\n', 1)
        resíduos[conexao] = restante
        comando = linha.strip(b'\r').split(b' ')
        validar_comando(conexao, comando)

def conexao_aceita(conexao):
    nicks[conexao] = b'*'
    print(conexao, 'nova conexão')
    conexao.registrar_recebedor(dados_recebidos)

def validar_nome(nome):
    return re.match(br'^[a-zA-Z][a-zA-Z0-9_-]*$', nome) is not None

## Integração com as demais camadas

nossa_ponta = '192.168.200.4'
outra_ponta = '192.168.200.3'
porta_tcp = 7000

driver = ZyboSerialDriver()
linha_serial = driver.obter_porta(0)

enlace = CamadaEnlace({outra_ponta: linha_serial})
rede = IP(enlace)
rede.definir_endereco_host(nossa_ponta)
rede.definir_tabela_encaminhamento([
    ('0.0.0.0/0', outra_ponta)
])
servidor = Servidor(rede, porta_tcp)
servidor.registrar_monitor_de_conexoes_aceitas(conexao_aceita)
asyncio.get_event_loop().run_forever()
