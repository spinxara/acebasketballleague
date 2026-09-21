import random

def weighted_order(teams, weights):
    """
    teams: list[str]
    weights: list[float] (same length as teams)
    returns: shuffled list based on weights (no duplicates)
    """
    remaining_teams = teams[:]
    remaining_weights = weights[:]
    order = []

    while remaining_teams:
        pick = random.choices(remaining_teams, weights=remaining_weights, k=1)[0]
        idx = remaining_teams.index(pick)

        order.append(pick)
        remaining_teams.pop(idx)
        remaining_weights.pop(idx)

    return order


def weighted_snake_draft(teams, rounds):
    """
    teams: list[str]
    rounds: int
    """
    results = []

    # positional weights (index-based)
    position_weights = [15, 35, 50]  # first → last

    # Round 1: start with equal odds
    round_order = weighted_order(
        teams,
        [1] * len(teams)
    )
    results.append(round_order)

    for r in range(1, rounds):
        prev = results[-1]
        reversed_prev = list(reversed(prev))

        weights = position_weights[:len(reversed_prev)]

        round_order = weighted_order(reversed_prev, weights)
        results.append(round_order)

    return results


# Example usage
teams = ["KCN", "BK", "NPS"]
draft = weighted_snake_draft(teams, 6)

for i, rnd in enumerate(draft, start=1):
    print(f"Round {i}: {rnd}")



