int square(int x) {
    return x * x;
}

int unused(void) {
    return 100;
}

int calculate(int a) {
    return square(a) + 1;
}

int main(void) {
    int result = calculate(5);
    return result;
}
