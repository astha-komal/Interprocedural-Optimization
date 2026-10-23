/* function_pointers.c
 * Function-pointer assignment and indirect-call resolution (T02, T03).
 * fp is assigned at declaration time; gp is declared first and assigned
 * later, exercising both pointer-discovery code paths.
 */
int square(int x) {
    return x * x;
}

int increment(int x) {
    return x + 1;
}

int main() {
    int (*fp)(int) = square;
    int a = fp(5);

    int (*gp)(int);
    gp = increment;
    int b = gp(a);

    return a + b;
}
