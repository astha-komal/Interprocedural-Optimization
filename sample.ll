define i32 @square(i32 %x) {
entry:
  %mul = mul i32 %x, %x
  ret i32 %mul
}

define i32 @unused() {
entry:
  ret i32 100
}

define i32 @calculate(i32 %a) {
entry:
  %call = call i32 @square(i32 %a)
  %add = add i32 %call, 1
  ret i32 %add
}

define i32 @main() {
entry:
  %call = call i32 @calculate(i32 5)
  ret i32 %call
}
