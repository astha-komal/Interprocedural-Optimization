#include <stdio.h>
/* square(7) in a comment must stay */
int square(int x) { return x * x; }
int sub(int a, int b) { return a - b; }
int third(int a) { return a / 3; }
int twice(int x) { return x + x; }
int neg(int x) { return -x; }
int helper(int k) { return square(k) + 1; }
int unused(int z) { return z; }

int main() {
    int n = 4, i = 0;
    int a = square(square(3));       /* nested constants */
    int b = square(n);               /* runtime arg -> inline */
    int c = sub(n, 10);              /* const arg mixed */
    int d = sub(i + 1, n - 2);       /* needs parens, order matters */
    int e = third(10);               /* division: not folded */
    int f = twice(i++);              /* side effect, param used twice -> keep call */
    int g = square(5) + neg(-2);
    printf("square(5)=%d\n", square(2));
    printf("%d %d %d %d %d %d %d %d\n", a, b, c, d, e, f, g, i);
    return a + b + c + d + e + f + g + helper(2);
}