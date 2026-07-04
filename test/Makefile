optional_cxxflags = \
	-std=c++20 \
	-ftabstop=2 \
	-Werror \
	-Wfatal-errors \
	-pedantic \
	-pedantic-errors \
	-Wabi=0 \
	-Waligned-new=all \
	-Wall \
	-Walloc-zero \
	-Walloca \
	-Warith-conversion \
	-Warray-bounds=2 \
	-Warray-parameter=2 \
	-Wattribute-alias=2 \
	-Wcast-align=strict \
	-Wcast-qual \
	-Wcatch-value=3 \
	-Wconditionally-supported \
	-Wconversion \
	-Wctad-maybe-unsupported \
	-Wctor-dtor-privacy \
	-Wdate-time \
	-Wdisabled-optimization \
	-Wdouble-promotion \
	-Wduplicated-branches \
	-Wduplicated-cond \
	-Weffc++ \
	-Wenum-conversion \
	-Wextra \
	-Wextra-semi \
	-Wfloat-equal \
	-Wformat=2 \
	-Wformat-overflow=2 \
	-Wformat-signedness \
	-Wformat-truncation=2 \
	-Wimplicit-fallthrough=3 \
	-Winline \
	-Winvalid-imported-macros \
	-Winvalid-pch \
	-Wlogical-op \
	-Wlong-long \
	-Wmismatched-tags \
	-Wmissing-braces \
	-Wmissing-include-dirs \
	-Wmultiple-inheritance \
	-Wnormalized=nfkc \
	-Wnull-dereference \
	-Wold-style-cast \
	-Woverloaded-virtual \
	-Wpacked \
	-Wpadded \
	-Wplacement-new=2 \
	-Wpointer-arith \
	-Wredundant-decls \
	-Wredundant-tags \
	-Wshadow \
	-Wsign-conversion \
	-Wsign-promo \
	-Wstrict-null-sentinel \
	-Wstrict-overflow=5 \
	-Wstringop-overflow=4 \
	-Wsuggest-attribute=cold \
	-Wsuggest-attribute=const \
	-Wsuggest-attribute=format \
	-Wsuggest-attribute=malloc \
	-Wsuggest-attribute=noreturn \
	-Wsuggest-attribute=pure \
	-Wsuggest-final-methods \
	-Wsuggest-final-types \
	-Wsuggest-override \
	-Wswitch-default \
	-Wswitch-enum \
	-Wsync-nand \
	-Wtrampolines \
	-Wundef \
	-Wunsafe-loop-optimizations \
	-Wunused-macros \
	-Wuseless-cast \
	-Wvector-operation-performance \
	-Wvirtual-inheritance \
	-Wvla \
	-Wzero-as-null-pointer-constant
# Omitted because they were being triggered:
# -Wsystem-headers
# -Wabi-tag
# -Waggregate-return
# -Wmissing-declarations
# -Wnamespaces
# -Wtemplates
# Not recognized by compiler:
# -Wbidi-chars=any
# -Winterference-size
# -Wopenacc-parallelism

ifeq ($(shell uname -o),Msys)
	optional_cxxflags += -static
endif

CXX=g++

CXXFLAGS = $(optional_cxxflags)

# Interpreter and seed count for the independent invariant campaign
# (invariants.py). Override e.g. with `make run PYTHON=python INVARIANT_SEEDS=6`.
PYTHON ?= python3
INVARIANT_SEEDS ?= 3

TESTS = tests

TEST_SOURCES = $(shell find $(TESTS) -name "*.cpp")
TEST_IDS = $(patsubst $(TESTS)/%.cpp, %, $(TEST_SOURCES))

.DELETE_ON_ERROR:

all: bbpPairingsTests.exe
.PHONY: all

test-includes.h: $(TESTS)
	echo > $@
	$(foreach \
		test_id, \
		$(TEST_IDS), \
		echo "#define TEST_ID $(test_id)" >> $@; \
			echo "#include <tests/$(test_id).cpp>" >> $@; \
			echo "#undef TEST_ID" >> $@;)
	echo >> $@
	echo "int runTests(const testing::Context &context)" >> $@
	echo { >> $@
	echo "  BEFORE_RUNNING_TESTS" >> $@
	$(foreach test_id, $(TEST_IDS), echo "  RUN_TEST($(test_id))" >> $@;)
	echo "  AFTER_RUNNING_TESTS" >> $@
	echo } >> $@

bbpPairingsTests.exe: test-includes.h main.cpp
	$(CXX) -o $@ -I. -MMD -MP main.cpp $(CXXFLAGS)

-include bbpPairingsTests.d

run: bbpPairingsTests.exe
	./bbpPairingsTests.exe ../bbpPairings.exe $(TESTS)
	$(MAKE) cli
	$(MAKE) invariants
.PHONY: run

# Portable CLI behaviour / exit-code tests (no-valid-pairing, invalid input,
# file error, unrated players, half-point byes, forfeits, Dutch checker).
cli:
	$(PYTHON) cli_tests.py --exe ../bbpPairings.exe
.PHONY: cli

# Oracle-independent validation: generate many tournaments with the engine and
# assert the hard FIDE invariants (no repeat game, symmetric pairings, no
# same-team pairing) hold. Requires Python 3 and a built ../bbpPairings.exe.
invariants:
	$(PYTHON) invariants.py --exe ../bbpPairings.exe --campaign --seeds $(INVARIANT_SEEDS)
.PHONY: invariants

clean:
	$(RM) -r $(TESTS)/*.output
	$(RM) -r bbpPairingsTests.*
	$(RM) -r test-includes.h
.PHONY: clean
