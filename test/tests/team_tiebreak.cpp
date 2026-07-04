// Regression test for team-standings tie-breaking and uneven team sizes.
// Team A (one member, 2.0 points) and Team B (two members, 1.0 + 1.0 = 2.0
// points) are tied on total score, but Team B's members faced higher-scoring
// opponents, so its team Buchholz (3.0) exceeds Team A's (2.0) and Team B is
// ranked first. Pins both the next-round pairing and the -t standings output.
void TEST_FUNCTION(const testing::Context &context)
{
  auto pairing_filename = STRINGIFY(TEST_ID) ".output";
  auto standings_filename = STRINGIFY(TEST_ID) ".teams";
  testing::run(
    context.exe_path.string()
    + " --dutch "
    + (context.data_folder_path / STRINGIFY(TEST_ID) ".input").string()
    + " -p "
    + pairing_filename
    + " -t "
    + standings_filename);
  testing::assert_file_content_matches(
    context.data_folder_path / pairing_filename,
    context.data_folder_path / STRINGIFY(TEST_ID) ".output.expected");
  testing::assert_file_content_matches(
    context.data_folder_path / standings_filename,
    context.data_folder_path / STRINGIFY(TEST_ID) ".teams.expected");
}
