/* boundary_cases.c
 * Boundary conditions (T07, T09):
 *   - get_zero(): a function with no parameters.
 *   - this file deliberately has NO main() function, to exercise the
 *     "missing entry point" boundary case (T09).
 */
int get_zero() {
    return 0;
}

int helper(int x) {
    return get_zero() + x;
}
