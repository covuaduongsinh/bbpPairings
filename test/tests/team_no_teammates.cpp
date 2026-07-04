// Verifies team support: players declared on the same team (013 lines) are
// never paired against each other, and the -t option writes team standings
// ranked by the sum of the members' scores.
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
