#include <iostream>

using namespace std;

// Dead function (unreachable from main -> should be removed)
void unused_function() {
    cout << "I am unused" << endl;
}

// Inlinable pure helper function
inline int square(int x) {
    return x * x;
}

// Pure function with reference parameters
int add(const int& a, const int& b) {
    return a + b;
}

// Mutually recursive functions (Call graph cycle in C++)
bool is_odd(int n);

bool is_even(int n) {
    if (n == 0) {
        return true;
    }
    return is_odd(n - 1);
}

bool is_odd(int n) {
    if (n == 0) {
        return false;
    }
    return is_even(n - 1);
}

int main() {
    int n = 4;
    // Call site eligible for constant folding
    int s = square(5);
    // Call site eligible for inlining
    int sum = add(n, 20);

    cout << "square(5) = " << s << endl;
    cout << "add(n, 20) = " << sum << endl;
    cout << "is_even(6) = " << (is_even(6) ? "true" : "false") << endl;

    return 0;
}
