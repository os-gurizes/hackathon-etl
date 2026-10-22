SIDE_TEXT = {"attack": "no ataque", "defense": "na defesa"}


def number(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def percent(value: float) -> str:
    if 0 < value < 0.1:
        return f"{number(value * 100)}%"
    return f"{round(value * 100)}%"


def rounds_text(value: float) -> str:
    rounded = round(value, 1)
    return f"{number(rounded)} round" if rounded == 1 else f"{number(rounded)} rounds"


def times(n: int) -> str:
    return "1 vez" if n == 1 else f"{n} vezes"


def severity_for_cost(cost_rounds: float) -> int:
    if cost_rounds >= 2:
        return 3
    if cost_rounds >= 1:
        return 2
    return 1


def first_death_zone(map_name: str, side: str, zone: str, rate: float, baseline: float, cost: float,
                     matches: int) -> tuple[str, str]:
    return (
        f"Você morre primeiro em {zone}",
        f"No {map_name}, {SIDE_TEXT[side]}, você é o primeiro do time a morrer em {zone} em {percent(rate)} dos "
        f"rounds. A média dos jogadores nessa zona é {percent(baseline)}. Em {matches} partidas, isso custou "
        f"cerca de {rounds_text(cost)}.",
    )


def isolated_death(map_name: str, side: str, rate: float, baseline: float, cost: float, matches: int) -> tuple[str, str]:
    return (
        "Mortes sem apoio do time",
        f"No {map_name}, {SIDE_TEXT[side]}, você morre sem nenhum aliado por perto e sem ser trocado em "
        f"{percent(rate)} dos rounds. Para a sua função, a média é {percent(baseline)}. Em {matches} partidas, "
        f"isso custou cerca de {rounds_text(cost)}.",
    )


def predictable_route(map_name: str, side: str, rate: float, baseline: float, cost: float) -> tuple[str, str]:
    return (
        "Rota fácil de prever",
        f"No {map_name}, {SIDE_TEXT[side]}, você começa os rounds quase sempre no mesmo lugar e é o primeiro a "
        f"morrer em {percent(rate)} deles. A média é {percent(baseline)}. Variar o caminho pode evitar cerca de "
        f"{rounds_text(cost)}.",
    )


def repeat_after_first_death(map_name: str, side: str, occurrences: int, cost: float) -> tuple[str, str]:
    return (
        "Repetição depois de morrer primeiro",
        f"No {map_name}, {SIDE_TEXT[side]}, depois de morrer primeiro numa zona você voltou a morrer primeiro no "
        f"mesmo lugar no round seguinte {times(occurrences)}. Isso custou cerca de {rounds_text(cost)}.",
    )


WATCH_NOTE = "Por enquanto é um indício: com mais partidas fica claro se é um padrão."

TEAM_ECONOMY = {
    "broken_economy": (
        "Economia quebrada depois de meia compra",
        "Em {k} de {n} meias compras o time perdeu e ficou sem dinheiro para comprar completo no round seguinte "
        "({rate}). A média dos times é {base}.",
    ),
    "eco_without_damage": (
        "Ecos sem dano",
        "Em {k} de {n} rounds de eco o time causou menos de 250 de dano no total ({rate}). A média dos times é "
        "{base}. Mesmo em eco, tirar vida dos adversários ajuda o round seguinte.",
    ),
    "full_buy_lost_to_eco": (
        "Derrotas com compra completa contra eco",
        "Em {k} de {n} rounds de compra completa contra eco o time perdeu ({rate}). A média dos times é {base}.",
    ),
    "force_after_pistol_loss": (
        "Compra forçada depois de perder o pistol",
        "O time forçou a compra em {k} de {n} rounds depois de perder o pistol ({rate}). A média dos times é {base}.",
    ),
}

ECONOMY = {
    "did_not_drop": (
        "Dinheiro sobrando com aliado sem arma",
        "Em {n} rounds você terminou a compra com dinheiro sobrando enquanto um aliado jogou praticamente sem "
        "arma. Comprar para o aliado deixa o time mais forte. Custo estimado: {cost}.",
    ),
    "saved_while_team_bought": (
        "Guardou dinheiro com o time comprando",
        "Em {n} rounds você guardou dinheiro enquanto o resto do time comprou completo. Custo estimado: {cost}.",
    ),
    "buy_out_of_sync": (
        "Compra fora do ritmo do time",
        "Em {n} rounds você comprou completo enquanto o time economizava. Custo estimado: {cost}.",
    ),
}

PRESSURE_TEXT = {
    "disadvantage": "em desvantagem numérica",
    "clutch": "quando fica sozinho contra o time adversário",
    "post_plant": "depois que a spike é plantada",
    "low_clock": "com pouco tempo no relógio, antes do plant",
    "losing_streak": "depois de 3 rounds perdidos seguidos",
    "match_point": "em match point",
    "eco_vs_full_buy": "em eco contra compra completa",
    "advantage": "em vantagem numérica",
}


def pressure_drop(context: str, kd: float, own_kd: float, baseline: float) -> tuple[str, str]:
    return (
        "Queda de rendimento sob pressão",
        f"{PRESSURE_TEXT[context].capitalize()}, seu K/D cai para {number(kd, 2)}. No geral ele é "
        f"{number(own_kd, 2)}, e a média dos jogadores nessa situação é {number(baseline, 2)}.",
    )


def clutch_strength(won: int, attempts: int, rate: float, baseline: float) -> tuple[str, str]:
    return (
        "Bom em situações de clutch",
        f"Você venceu {won} de {attempts} rounds em que ficou sozinho contra o adversário ({percent(rate)}). "
        f"A média é {percent(baseline)}.",
    )


def rotation_without_info(n: int, fell_rate: float, informed_rate: float) -> tuple[str, str]:
    return (
        "Rotações sem informação na defesa",
        f"Na defesa, jogadores do time saíram de um site sem nenhuma informação do outro {times(n)}. Nesses casos "
        f"o site abandonado recebeu o plant em {percent(fell_rate)} das vezes, contra {percent(informed_rate)} "
        f"quando a rotação tinha informação.",
    )


def overuse(matches: int, total: int) -> tuple[str, str]:
    return (
        "Habilidades usadas sem retorno",
        f"Em {matches} de {total} partidas você usou habilidades bem mais que a média do seu agente no mapa, sem "
        f"mais abates ou assistências por isso. Esta é uma estimativa: o jogo não registra o momento de cada uso.",
    )


def ult_in_decided_rounds(n: int, total: int) -> tuple[str, str]:
    return (
        "Ultimates em rounds já decididos",
        f"{n} dos {total} abates com ultimate aconteceram em rounds que já estavam praticamente ganhos ou "
        f"perdidos. Guardar a ultimate para um round disputado rende mais. Esta é uma estimativa.",
    )


def strategy(map_name: str, side: str, title: str, rate: float, rounds: int, best: bool) -> tuple[str, str]:
    if best:
        return (
            "Estratégia que mais funciona",
            f"No {map_name}, {SIDE_TEXT[side]}, \"{title}\" é a estratégia que mais deu certo para o time: "
            f"{percent(rate)} de vitória em {rounds} rounds.",
        )
    return (
        "Estratégia com pior resultado",
        f"No {map_name}, {SIDE_TEXT[side]}, \"{title}\" é a estratégia com pior resultado do time: "
        f"{percent(rate)} de vitória em {rounds} rounds.",
    )


def combo(player_a: str, player_b: str, map_name: str, n: int, control: float, team_control: float) -> tuple[str, str]:
    return (
        "Dupla que funciona",
        f"No {map_name}, quando {player_a} ajuda e {player_b} finaliza, o time domina o site em "
        f"{percent(control)} das {n} vezes, contra {percent(team_control)} nas outras jogadas do time. "
        f"Esta é uma estimativa.",
    )


def best_agent(agent: str, map_name: str, acs: float, baseline: float, matches: int) -> tuple[str, str]:
    return (
        f"Seu melhor agente no {map_name}",
        f"Com {agent} no {map_name} você tem média de {round(acs)} de pontuação por round em {matches} partidas. "
        f"A média do agente nesse mapa é {round(baseline)}.",
    )


def best_map(map_name: str, kd: float, own_kd: float, matches: int) -> tuple[str, str]:
    return (
        "Seu melhor mapa",
        f"No {map_name} seu K/D é {number(kd, 2)} em {matches} partidas, acima da sua média geral de "
        f"{number(own_kd, 2)}.",
    )
