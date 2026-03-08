from itertools import permutations, combinations

def optimizeReservedConcurrency(conc, price):
    n = len(conc)
    
    # Generate all possible target values we might need
    min_val = min(conc)
    max_val = max(conc) + n
    
    min_cost = float('inf')
    
    # Try all possible sets of n unique values
    for target_set in combinations(range(min_val, max_val + 1), n):
        # Try all permutations of assigning these targets to functions
        for target_perm in permutations(target_set):
            cost = 0
            valid = True
            
            # Calculate cost for this assignment
            for i in range(n):
                if target_perm[i] < conc[i]:
                    valid = False
                    break
                cost += (target_perm[i] - conc[i]) * price[i]
            
            if valid and cost < min_cost:
                min_cost = cost
    
    return min_cost

# Test all cases
print("Test 1:", optimizeReservedConcurrency([8, 6, 8], [9, 5, 7]))  # Expected: 7
print("Test 2:", optimizeReservedConcurrency([3, 5], [1, 7]))        # Expected: 0  
print("Test 3:", optimizeReservedConcurrency([5, 2, 5, 3, 3], [3, 7, 8, 6, 9]))  # Expected: 9