/*
 * long_stress_test.c
 * Stress test for an interprocedural optimizer.
 * Sections:
 *   1. Constant folding candidates
 *   2. Single-caller functions (inlining candidates)
 *   3. Multi-caller functions (should NOT be blindly inlined)
 *   4. Dead functions (direct + transitively dead chain)
 *   5. Direct recursion and mutual recursion
 *   6. Function pointers (address-taken => NOT dead)
 *   7. Side effects (global state) that must be preserved
 *   8. Nested calls and constant arguments across call boundaries
 *   9. Pointer parameters / aliasing
 */
#include <stdio.h>

/* ---------- globals (side effects) ---------- */
int g_counter = 0;
int g_log[16];
int g_log_len = 0;

/* ---------- 1. constant folding ---------- */
int const_expr(void) {
    return (3 + 4) * 5 - 2;          /* folds to 33 */
}

int const_chain(void) {
    int a = 10;
    int b = a * 2;                   /* 20 */
    int c = b + 5;                   /* 25 */
    return c * 2;                    /* 50 */
}

int always_ten(int ignored) {
    (void)ignored;
    return 10;
}

/* ---------- 2. single-caller functions ---------- */
int square(int x) {
    return x * x;
}

int cube_via_square(int x) {         /* only caller of square */
    return square(x) * x;
}

int add_five(int x) {
    return x + 5;
}

int only_called_once(int a, int b) {
    return add_five(a) + b;
}

/* ---------- 3. multi-caller functions ---------- */
int clamp(int v, int lo, int hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

int scale_a(int v) {
    return clamp(v * 3, 0, 100);
}

int scale_b(int v) {
    return clamp(v * 7, 0, 50);
}

int scale_c(int v) {
    return clamp(v - 20, -10, 10);
}

/* ---------- 4. dead code ---------- */
int dead_leaf(int x) {
    return x * 1000;
}

int dead_mid(int x) {
    return dead_leaf(x) + 1;
}

int dead_top(int x) {
    return dead_mid(x) + dead_leaf(x);
}

int never_called_with_side_effect(void) {
    g_counter += 999;
    return g_counter;
}

/* ---------- 5. recursion ---------- */
int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}

int fib(int n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

int is_odd(int n);
int is_even(int n) {
    if (n == 0) return 1;
    return is_odd(n - 1);
}
int is_odd(int n) {
    if (n == 0) return 0;
    return is_even(n - 1);
}

int sum_to(int n) {
    if (n == 0) return 0;
    return n + sum_to(n - 1);
}

/* ---------- 6. function pointers ---------- */
typedef int (*binop)(int, int);

int op_add(int a, int b) { return a + b; }
int op_sub(int a, int b) { return a - b; }
int op_mul(int a, int b) { return a * b; }
int op_max(int a, int b) { return a > b ? a : b; }

/* never called by name; only reachable through the table below */
int op_hidden(int a, int b) { return (a ^ b) + 1; }

binop op_table[5] = { op_add, op_sub, op_mul, op_max, op_hidden };

int apply_op(binop f, int a, int b) {
    return f(a, b);
}

int dispatch(int idx, int a, int b) {
    return op_table[idx](a, b);
}

/* ---------- 7. side effects ---------- */
void log_value(int v) {
    if (g_log_len < 16) {
        g_log[g_log_len++] = v;
    }
}

int bump(void) {
    g_counter++;
    return g_counter;
}

int logged_square(int x) {
    int r = square(x);               /* second caller of square */
    log_value(r);
    return r;
}

int impure_twice(void) {
    return bump() + bump();          /* evaluation order matters */
}

/* ---------- 8. nested calls / constant args ---------- */
int level3(int x) { return x + 1; }
int level2(int x) { return level3(x) * 2; }
int level1(int x) { return level2(x) + level2(x + 1); }

int const_arg_user(int mode) {
    if (mode == 0) return 100;
    if (mode == 1) return 200;
    return 300;
}

int call_with_consts(void) {
    return const_arg_user(0) + const_arg_user(1) + const_arg_user(2);
}

/* ---------- 9. pointers / aliasing ---------- */
void swap(int *a, int *b) {
    int t = *a;
    *a = *b;
    *b = t;
}

void add_into(int *dst, int *src) {
    *dst += *src;
}

int alias_test(void) {
    int x = 5, y = 9;
    int *p = &x;
    int *q = &x;                     /* p and q alias */
    *p = 20;
    int r1 = *q;                     /* must be 20 */
    swap(&x, &y);                    /* x=9, y=20 */
    add_into(&x, &y);                /* x=29 */
    return r1 + x + y;               /* 20 + 29 + 20 = 69 */
}

int array_sum(int *arr, int n) {
    int s = 0;
    for (int i = 0; i < n; i++) s += arr[i];
    return s;
}

/* ---------- main ---------- */
int main(void) {
    int checksum = 0;

    printf("const_expr        = %d\n", const_expr());
    checksum += const_expr();
    printf("const_chain       = %d\n", const_chain());
    checksum += const_chain();
    printf("always_ten(7)     = %d\n", always_ten(7));
    checksum += always_ten(7);

    printf("cube_via_square(4)= %d\n", cube_via_square(4));
    checksum += cube_via_square(4);
    printf("only_called_once  = %d\n", only_called_once(3, 4));
    checksum += only_called_once(3, 4);

    printf("scale_a(10)       = %d\n", scale_a(10));
    printf("scale_b(10)       = %d\n", scale_b(10));
    printf("scale_c(10)       = %d\n", scale_c(10));
    checksum += scale_a(10) + scale_b(10) + scale_c(10);

    printf("factorial(6)      = %d\n", factorial(6));
    printf("fib(10)           = %d\n", fib(10));
    printf("is_even(10)       = %d\n", is_even(10));
    printf("is_odd(7)         = %d\n", is_odd(7));
    printf("sum_to(10)        = %d\n", sum_to(10));
    checksum += factorial(6) + fib(10) + is_even(10) + is_odd(7) + sum_to(10);

    for (int i = 0; i < 5; i++) {
        printf("dispatch(%d,12,5)  = %d\n", i, dispatch(i, 12, 5));
        checksum += dispatch(i, 12, 5);
    }
    printf("apply_op(mul,6,7) = %d\n", apply_op(op_mul, 6, 7));
    checksum += apply_op(op_mul, 6, 7);

    printf("logged_square(5)  = %d\n", logged_square(5));
    printf("logged_square(6)  = %d\n", logged_square(6));
    printf("impure_twice      = %d\n", impure_twice());
    printf("g_counter         = %d\n", g_counter);
    printf("g_log_len         = %d\n", g_log_len);
    checksum += g_counter + g_log_len;

    printf("level1(3)         = %d\n", level1(3));
    printf("call_with_consts  = %d\n", call_with_consts());
    checksum += level1(3) + call_with_consts();

    printf("alias_test        = %d\n", alias_test());
    int arr[6] = { 1, 2, 3, 4, 5, 6 };
    printf("array_sum         = %d\n", array_sum(arr, 6));
    checksum += alias_test() + array_sum(arr, 6);

    printf("checksum          = %d\n", checksum);
    return checksum % 256;
}