/* direct_calls.c
 * Straight-line direct function calls, including one call with a constant
 * argument (for constant-propagation testing, T11) and one with a runtime
 * argument (not constant-foldable).
 */
int square(int x) {
    return x * x;
}

int add(int a, int b) {
    return a + b;
}

int compute(int n) {
    int s = square(5);      /* constant argument -> constant_propagation fires */
    int t = add(n, 2);      /* runtime argument  -> not constant-foldable */
    return s + t;
}

int main() {
    int result = compute(10);
    return result;
}
