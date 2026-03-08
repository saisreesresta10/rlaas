from itertools import permutations, combinations

def optimizeReservedConcurrency(conc, price):
    """Optimized version with early pruning and smaller search space"""
    n = len(conc)
    
    # Optimization 1: Reduce search space
    min_val = min(conc)
    # We only need at most n additional values beyond max
    max_val = max(conc) + n
    
    min_cost = float('inf')
    
    # Optimization 2: Try smaller ranges first (likely to find good solutions early)
    for range_size in range(n, max_val - min_val + 2):
        for start in range(min_val, max_val - range_size + 2):
            target_set = tuple(range(start, start + range_size))
            
            # Try all combinations of n values from this range
            for target_subset in combinations(target_set, n):
                # Optimization 3: Use Hungarian algorithm or greedy for assignment
                cost = find_optimal_assignment(conc, price, target_subset)
                if cost < min_cost:
                    min_cost = cost
                    
                # Optimization 4: Early termination if we find cost 0
                if min_cost == 0:
                    return 0
    
    return min_cost

def find_optimal_assignment(conc, price, targets):
    """Find optimal assignment using Hungarian-like approach"""
    n = len(conc)
    min_cost = float('inf')
    
    # Try all permutations (still exponential but with pruning)
    for target_perm in permutations(targets):
        cost = 0
        valid = True
        
        for i in range(n):
            if target_perm[i] < conc[i]:
                valid = False
                break
            cost += (target_perm[i] - conc[i]) * price[i]
            
            # Early pruning: if cost already exceeds current minimum
            if cost >= min_cost:
                valid = False
                break
        
        if valid and cost < min_cost:
            min_cost = cost
    
    return min_cost if min_cost != float('inf') else float('inf')

# More efficient version using greedy approach (may not be optimal but much faster)
def optimizeReservedConcurrencyGreedy(conc, price):
    """Greedy approach - much faster but may not be globally optimal"""
    n = len(conc)
    pairs = list(zip(conc, price))
    pairs.sort()  # Sort by concurrency
    
    total_cost = 0
    used = set()
    
    for curr_conc, curr_price in pairs:
        target = curr_conc
        while target in used:
            target += 1
        
        used.add(target)
        total_cost += (target - curr_conc) * curr_price
    
    return total_cost

# Test both approaches
def test_both_approaches():
    test_cases = [
        ([8, 6, 8], [9, 5, 7], 7),
        ([3, 5], [1, 7], 0),
        ([5, 2, 5, 3, 3], [3, 7, 8, 6, 9], 9)
    ]
    
    for i, (conc, price, expected) in enumerate(test_cases, 1):
        optimal = optimizeReservedConcurrency(conc, price)
        greedy = optimizeReservedConcurrencyGreedy(conc, price)
        
        print(f"Test {i}: conc={conc}, price={price}")
        print(f"Expected: {expected}")
        print(f"Optimal:  {optimal} {'✓' if optimal == expected else '✗'}")
        print(f"Greedy:   {greedy} {'✓' if greedy == expected else '✗'}")
        print()

if __name__ == "__main__":
    test_both_approaches()