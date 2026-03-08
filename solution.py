from itertools import permutations, combinations

def optimizeReservedConcurrency(conc, price):
    """
    Find minimum cost to make all concurrency values unique by only increasing them.
    
    Args:
        conc: List of current concurrency values
        price: List of prices for increasing each function's concurrency by 1
    
    Returns:
        Minimum cost to make all values unique
    """
    n = len(conc)
    
    # Generate range of possible target values
    min_val = min(conc)
    max_val = max(conc) + n  # Upper bound: worst case all need to be increased
    
    min_cost = float('inf')
    
    # Try all possible sets of n unique values from the range
    for target_set in combinations(range(min_val, max_val + 1), n):
        # Try all permutations of assigning these targets to functions
        for target_perm in permutations(target_set):
            cost = calculate_assignment_cost(conc, price, target_perm)
            if cost < min_cost:
                min_cost = cost
    
    return min_cost

def calculate_assignment_cost(conc, price, targets):
    """Calculate total cost for a specific assignment of target values"""
    total_cost = 0
    
    for i in range(len(conc)):
        if targets[i] < conc[i]:
            return float('inf')  # Invalid: can't decrease concurrency
        
        cost = (targets[i] - conc[i]) * price[i]
        total_cost += cost
    
    return total_cost

# Test cases
def test_all_cases():
    # Test case 1
    conc1 = [8, 6, 8]
    price1 = [9, 5, 7]
    result1 = optimizeReservedConcurrency(conc1, price1)
    print(f"Test 1: conc={conc1}, price={price1}")
    print(f"Result: {result1}, Expected: 7")
    print()
    
    # Test case 2
    conc2 = [3, 5]
    price2 = [1, 7]
    result2 = optimizeReservedConcurrency(conc2, price2)
    print(f"Test 2: conc={conc2}, price={price2}")
    print(f"Result: {result2}, Expected: 0")
    print()
    
    # Test case 3
    conc3 = [5, 2, 5, 3, 3]
    price3 = [3, 7, 8, 6, 9]
    result3 = optimizeReservedConcurrency(conc3, price3)
    print(f"Test 3: conc={conc3}, price={price3}")
    print(f"Result: {result3}, Expected: 9")
    print()

if __name__ == "__main__":
    test_all_cases()