class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/c7/99/3dde881b4a0e5239a47961f143e8347644dae44d755503c5d2e6f4a00326/agentops_mcp_server-0.0.6.tar.gz"
  sha256 "ecbc84230214a2bb12a7e479d319562a8d6154349c1b5e82b01da348e6ecafb4"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
