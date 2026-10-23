/* recursion.c
 * Direct recursion (recursive -> recursive, T06/T08) and mutual recursion
 * (even -> odd -> even, T04/T05).
 */
int recursive(int n) {
    if (n <= 0) {
        return 0;
    }
    return recursive(n - 1);
}

int even(int n);
int odd(int n);

int even(int n) {
    if (n == 0) {
        return 1;
    }
    return odd(n - 1);
}

int odd(int n) {
    if (n == 0) {
        return 0;
    }
    return even(n - 1);
}

int main() {
    int r = recursive(3);
    int e = even(4);
    return r + e;
}
