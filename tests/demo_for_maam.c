/* A simple program a student might submit for optimization. */
int cube(int x) {
    return x * x * x;
}

int double_it(int x) {
    return x + x;
}

int main() {
    int a = cube(3);
    int b = double_it(a);
    return b;
}
