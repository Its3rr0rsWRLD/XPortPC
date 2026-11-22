// Each import names a forwarder in intake_forward.dll. Static checks read this image; nothing runs it.
extern "C" __declspec(dllimport) int forwarded_value();
extern "C" __declspec(dllimport) int forwarded_ordinal();
extern "C" __declspec(dllimport) int forwarded_chain();
extern "C" __declspec(dllimport) int forwarded_missing();
extern "C" __declspec(dllimport) int forwarded_loop();
extern "C" __declspec(dllimport) int forwarded_absent();
extern "C" __declspec(dllimport) int forwarded_upper();

int main() {
    int (*volatile unresolved[])() = {&forwarded_missing, &forwarded_loop, &forwarded_absent};
    return forwarded_value() + forwarded_ordinal() + forwarded_chain() + forwarded_upper() + (unresolved[0] != nullptr);
}
