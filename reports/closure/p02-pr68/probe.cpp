// Validation-only observer of the production PersistentEngineSession.
#include "../../../src/runtime/engine.cpp"
#include <map>
#include <tuple>

struct Support { std::string region; double x; double y; };

int main(int argc, char** argv) {
  try {
    const auto options = parse_options(argc, argv);
    PersistentEngineSession session(options);
    session.set_protocol_version(4);
    std::vector<Support> support;
    std::string line;
    while (std::getline(std::cin, line)) {
      std::istringstream input(line);
      std::string kind;
      input >> kind;
      if (kind == "ROI") {
        Support s;
        if (!(input >> s.region >> s.x >> s.y)) throw std::invalid_argument("bad ROI");
        support.push_back(s);
      } else if (kind == "B") {
        std::size_t count;
        if (!(input >> count)) throw std::invalid_argument("bad binary count");
        session.ingest_binary(std::cin, count, 4);
        const auto& result = session.result();
        using Key = std::tuple<int, std::int64_t, std::int64_t>;
        std::map<Key, const veyra::map::CellStats*> index;
        for (const auto& leaf : result.snapshot.leaves)
          index.emplace(Key{leaf.id.level, leaf.id.ix, leaf.id.iy}, &leaf.stats);
        std::map<std::string, std::array<std::size_t, 3>> counts;
        for (const auto& s : support) {
          auto& c = counts[s.region];
          ++c[0];
          for (int level = 0; level < 4; ++level) {
            const double res = 0.05 * static_cast<double>(1 << level);
            const auto it = index.find(Key{level, static_cast<std::int64_t>(std::floor(s.x / res)),
                                          static_cast<std::int64_t>(std::floor(s.y / res))});
            if (it == index.end()) continue;
            ++c[1];
            if (it->second->occupancy() == veyra::map::OccupancyState::Occupied) ++c[2];
            break;
          }
        }
        std::string report = render(result);
        report.erase(report.find_last_not_of("\n") + 1);
        report.pop_back();
        report += ",\"seed_support\":{";
        bool first = true;
        for (const auto& [name, c] : counts) {
          if (!std::exchange(first, false)) report += ',';
          report += '"' + name + "\":{\"bins\":" + std::to_string(c[0]) +
                    ",\"resident\":" + std::to_string(c[1]) +
                    ",\"occupied\":" + std::to_string(c[2]) + '}';
        }
        std::cout << report << "}}\n" << std::flush;
      } else if (!line.empty()) {
        throw std::invalid_argument("unknown validation record");
      }
    }
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
